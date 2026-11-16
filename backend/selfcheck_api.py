"""04llm self-check. Run: python backend/selfcheck_api.py  (in-process; RESETS the DB; MySQL must be up)."""
import sys
import threading

import app as A
import config
import db
import init_db
from services import notify

flask_app = getattr(A, "app", None) or A.create_app()
SEEN, FAILS = [], []


def call(method, path, body=None, uid=None):
    r = flask_app.test_client().open("/api" + path, method=method, json=body,
                                     headers={"X-User-Id": str(uid)} if uid is not None else {})
    SEEN.append(r.get_data(as_text=True))
    return r.status_code, r.get_json(silent=True)


def code(res): return ((res[1] or {}).get("error") or {}).get("code")
def data(res): return (res[1] or {}).get("data")


def chk(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


init_db.reset_database(test_fixtures=True)
NEW = dict(username="dave", password="dave1234", full_name="Dave Rao", email="dave@x.test", phone="9876500010")
reg = lambda **o: call("POST", "/auth/register", {**NEW, **o})

# 1. register / login / profile
r = reg(); DAVE = data(r)["user"]["user_id"]
chk("register 201, keys user+account", r[0] == 201 and set(data(r)) == {"user", "account"})
chk("first account SAVINGS 0.00", data(r)["account"]["account_type"] == "SAVINGS" and data(r)["account"]["balance"] == "0.00")
chk("USERNAME_TAKEN", code(reg(email="d2@x.test")) == "USERNAME_TAKEN")
chk("EMAIL_TAKEN", code(reg(username="dave2")) == "EMAIL_TAKEN")
for f, v in [("username", "ab"), ("username", "bad name!"), ("password", "abc"), ("email", "no-at.test"),
             ("phone", "123456789"), ("date_of_birth", "31-12-1990")]:
    x = call("POST", "/auth/register", {**NEW, "username": "dave9", "email": "d9@x.test", f: v})
    chk(f"invalid {f}={v!r}", code(x) == "VALIDATION_ERROR" and f in x[1]["error"]["details"]["fields"])
a = call("POST", "/auth/login", {"username": "dave", "password": "wrong"})
b = call("POST", "/auth/login", {"username": "nobody", "password": "wrong"})
chk("wrong password == unknown user (identical)", a[0] == b[0] == 401 and a[1] == b[1] and code(a) == "INVALID_CREDENTIALS")
chk("__bank__ cannot log in", code(call("POST", "/auth/login", {"username": "__bank__", "password": "x"})) == "INVALID_CREDENTIALS")
l = call("POST", "/auth/login", {"username": "alice", "password": "alice123"})
chk("alice login + accounts", l[0] == 200 and data(l)["accounts"][0]["balance"] == "10000.00")
chk("GET /users/me", data(call("GET", "/users/me", uid=2))["user"]["username"] == "alice")
p = call("PUT", "/users/me", {"phone": "9999999999", "bogus": 1, "address": ""}, uid=2)
chk("PUT /users/me partial, blank->null, unknown ignored", data(p)["user"]["phone"] == "9999999999" and data(p)["user"]["address"] is None)
chk("PUT bad phone", code(call("PUT", "/users/me", {"phone": "1"}, uid=2)) == "VALIDATION_ERROR")
chk("PUT EMAIL_TAKEN", code(call("PUT", "/users/me", {"email": "bob@abcbank.test"}, uid=2)) == "EMAIL_TAKEN")

# 2. race
res = []
ts = [threading.Thread(target=lambda i=i: res.append(call("POST", "/auth/register", {**NEW, "username": "racer", "email": f"r{i}@x.test"}))) for i in range(10)]
[t.start() for t in ts]; [t.join() for t in ts]
outs = [str(code(x) or x[0]) for x in res]
chk("race: 1x201 + 9x USERNAME_TAKEN, 1 row", outs.count("201") == 1 and outs.count("USERNAME_TAKEN") == 9
    and db.fetch_one("SELECT COUNT(*) AS n FROM users WHERE username='racer'")["n"] == 1)

# 3. accounts
made = [call("POST", "/accounts", {"account_type": "CURRENT"}, uid=DAVE) for _ in range(4)]
chk("accounts 2..5 created", all(m[0] == 201 for m in made))
chk("6th LIMIT_EXCEEDED", code(call("POST", "/accounts", {"account_type": "CURRENT"}, uid=DAVE)) == "LIMIT_EXCEEDED")
chk("bad account_type", code(call("POST", "/accounts", {"account_type": "X"}, uid=DAVE)) == "VALIDATION_ERROR")
A2, A3 = (data(m)["account"]["account_id"] for m in made[:2])
st = lambda i, s, u=DAVE: call("PATCH", f"/accounts/{i}/status", {"status": s}, uid=u)
chk("freeze/unfreeze", data(st(A2, "FROZEN"))["account"]["status"] == "FROZEN" and data(st(A2, "ACTIVE"))["account"]["status"] == "ACTIVE")
chk("same status = no-op 200", st(A2, "ACTIVE")[0] == 200)
chk("close with balance -> INVALID_STATE", code(st(2, "CLOSED", 2)) == "INVALID_STATE")
loan = db.execute("INSERT INTO loans (user_id, account_id, status) VALUES (%s,%s,'ACTIVE')", (DAVE, A3))
chk("close with ACTIVE loan -> INVALID_STATE", code(st(A3, "CLOSED")) == "INVALID_STATE")
db.execute("DELETE FROM loans WHERE loan_id=%s", (loan,))
chk("close empty account", st(A3, "CLOSED")[0] == 200)
chk("CLOSED -> ACTIVE INVALID_STATE", code(st(A3, "ACTIVE")) == "INVALID_STATE")
E = reg(username="erin", email="erin@x.test")
chk("close last account -> INVALID_STATE", code(st(data(E)["account"]["account_id"], "CLOSED", data(E)["user"]["user_id"])) == "INVALID_STATE")
chk("other user's account FORBIDDEN / unknown NOT_FOUND", code(st(2, "FROZEN")) == "FORBIDDEN" and code(st(99999, "FROZEN")) == "NOT_FOUND")
chk("GET account FORBIDDEN / NOT_FOUND", code(call("GET", "/accounts/2", uid=DAVE)) == "FORBIDDEN" and code(call("GET", "/accounts/99999", uid=DAVE)) == "NOT_FOUND")
lk = lambda n: call("GET", "/accounts/lookup?account_number=" + n, uid=DAVE)
chk("lookup masks name", data(lk("100000000001"))["holder_name"] == "Alice S.")
chk("lookup system -> ACCOUNT_NOT_FOUND", code(lk("000000000001")) == "ACCOUNT_NOT_FOUND")
chk("lookup 11 digits -> VALIDATION_ERROR", code(lk("10000000000")) == "VALIDATION_ERROR")

# 4. auth header
AUTHED = [("GET", "/users/me"), ("PUT", "/users/me"), ("GET", "/accounts"), ("POST", "/accounts"), ("GET", "/accounts/lookup"),
          ("GET", "/accounts/2"), ("PATCH", "/accounts/2/status"), ("GET", "/notifications"), ("POST", "/notifications/1/read"),
          ("POST", "/notifications/read-all"), ("GET", "/dashboard")]
for m, pth in AUTHED:
    chk(f"AUTH_REQUIRED {m} {pth}", all(code(call(m, pth, uid=u)) == "AUTH_REQUIRED" for u in (None, "abc", 999999, 1)))
chk("public /system/health (status+db+server_time only)", call("GET", "/system/health")[0] == 200
    and set(data(call("GET", "/system/health"))) == {"status", "db", "server_time"})
OFF = 5  # officer user_id in the test fixtures
STAFF = [("GET", "/admin/overview"), ("GET", "/admin/integrity"), ("GET", "/admin/simulation"), ("PUT", "/admin/simulation"),
         ("POST", "/admin/reset"), ("GET", "/admin/customers"), ("GET", "/admin/transactions"), ("GET", "/admin/loans"),
         ("GET", "/admin/loans/1"), ("POST", "/admin/loans/1/review")]
for m, pth in STAFF:
    chk(f"staff-only {m} {pth}: no auth -> AUTH_REQUIRED, customer -> FORBIDDEN",
        code(call(m, pth)) == "AUTH_REQUIRED" and code(call(m, pth, uid=2)) == "FORBIDDEN")
chk("officer cannot use customer APIs (/dashboard, /accounts)", all(code(call("GET", p_, uid=OFF)) == "FORBIDDEN" for p_ in ("/dashboard", "/accounts")))
chk("old /system tools are gone", all(call(m, p_)[0] in (404, 405) for m, p_ in (("GET", "/system/simulation"), ("PUT", "/system/simulation"),
    ("POST", "/system/reset"), ("GET", "/system/integrity"))))
chk("customer /loans/{id}/review is gone", call("POST", "/loans/1/review", {"decision": "AUTO"}, uid=2)[0] in (404, 405))
ol = call("POST", "/auth/login", {"username": "officer", "password": "officer123"})
chk("officer login returns role OFFICER, customer role CUSTOMER", data(ol)["user"]["role"] == "OFFICER" and data(l)["user"]["role"] == "CUSTOMER")

# 5. dashboard (alice, seed money untouched)
d = data(call("GET", "/dashboard", uid=2))
chk("dashboard key set", set(d) == {"user", "primary_account", "total_balance", "recent_transactions", "unread_notifications",
                                    "active_loans", "next_installment", "promo"})
chk("dashboard values", d["primary_account"]["balance"] == "10000.00" and d["total_balance"] == "10000.00")
chk("dashboard seed transfer OUT", any(t["description"] == "Seed transfer" and t["direction"] == "OUT" for t in d["recent_transactions"]))

# 6. notifications
def fixtures(uid, n):
    with db.transaction() as cur:
        return [notify.create_notification(cur, uid, "DEPOSIT", f"t{i}", "m") for i in range(n)]
ids, alice_n = fixtures(3, 12), fixtures(2, 1)[0]
n = data(call("GET", "/notifications?page_size=5", uid=3))
chk("notif pagination/unread_count", n["total_items"] == 12 and n["total_pages"] == 3 and n["unread_count"] == 12 and len(n["items"]) == 5)
chk("mark one read", data(call("POST", f"/notifications/{ids[0]}/read", uid=3))["notification"]["is_read"] is True)
chk("unread_only filter", data(call("GET", "/notifications?unread_only=true&page_size=50", uid=3))["total_items"] == 11)
chk("foreign notification FORBIDDEN", code(call("POST", f"/notifications/{alice_n}/read", uid=3)) == "FORBIDDEN")
chk("unknown notification NOT_FOUND", code(call("POST", "/notifications/99999/read", uid=3)) == "NOT_FOUND")
chk("read-all count 11 then 0", data(call("POST", "/notifications/read-all", uid=3))["updated"] == 11
    and data(call("POST", "/notifications/read-all", uid=3))["updated"] == 0)

# 7. integrity mutation tests
integ = lambda: data(call("GET", "/admin/integrity", uid=OFF))
chk("integrity ok before mutations", integ()["ok"] is True)
REF = "00000000-0000-4000-8000-000000000001"
def mutate(name, brk, fix):
    [db.execute(s) for s in brk]
    r = integ()
    chk(f"{name} flips false with violations + health DEGRADED", r["ok"] is False and not r["checks"][name]["ok"]
        and r["checks"][name]["violations"] and data(call("GET", "/system/health"))["status"] == "DEGRADED"
        and data(call("GET", "/admin/overview", uid=OFF))["health"]["status"] == "DEGRADED")
    [db.execute(s) for s in fix]
    chk(f"{name} repaired -> ok", integ()["ok"] is True)
mutate("I2", ["UPDATE accounts SET balance=balance+1 WHERE account_id=3"], ["UPDATE accounts SET balance=balance-1 WHERE account_id=3"])
mutate("I1", ["CREATE TABLE _bak SELECT * FROM ledger_entries WHERE entry_id=8", "DELETE FROM ledger_entries WHERE entry_id=8"],
       ["INSERT INTO ledger_entries SELECT * FROM _bak", "DROP TABLE _bak"])
mutate("I3", [f"INSERT INTO transactions (txn_ref,txn_type,from_account_id,to_account_id,amount,status,failure_code) VALUES ('{REF}','TRANSFER',2,3,1.00,'FAILED','X')",
              f"INSERT INTO ledger_entries (txn_id,account_id,entry_type,amount,balance_after) SELECT txn_id,2,'DEBIT',1.00,0 FROM transactions WHERE txn_ref='{REF}'"],
       [f"DELETE FROM ledger_entries WHERE txn_id=(SELECT txn_id FROM transactions WHERE txn_ref='{REF}')", f"DELETE FROM transactions WHERE txn_ref='{REF}'"])
mutate("I4", ["INSERT INTO accounts (account_number,user_id,balance) VALUES ('999999999999',2,5.00)"], ["DELETE FROM accounts WHERE account_number='999999999999'"])
mutate("I5", ["ALTER TABLE accounts ALTER CHECK chk_accounts_balance NOT ENFORCED", "UPDATE accounts SET balance=-1 WHERE account_id=4"],
       ["UPDATE accounts SET balance=25000 WHERE account_id=4", "ALTER TABLE accounts ALTER CHECK chk_accounts_balance ENFORCED"])
mutate("I6", ["INSERT INTO loans (user_id,account_id,status,tenure_months,approved_amount) VALUES (2,2,'ACTIVE',6,5000)"], ["DELETE FROM loans WHERE status='ACTIVE'"])

# 8. simulation control
SIM = lambda **b: call("PUT", "/admin/simulation", b, uid=OFF)
for m in ("NONE", "BEFORE_DEBIT", "AFTER_DEBIT", "BEFORE_COMMIT", "DROP_RESPONSE", "RANDOM"):
    put, got, h = SIM(mode=m), data(call("GET", "/admin/simulation", uid=OFF)), data(call("GET", "/admin/overview", uid=OFF))["health"]["status"]
    chk(f"simulation {m}", put[0] == 200 and got["mode"] == m and h == ("ALL_GOOD" if m == "NONE" else "SIMULATION_ACTIVE"))
chk("6 modes listed", len(got["modes"]) == 6)
chk("invalid mode / probability 1.5", code(SIM(mode="BOGUS")) == "VALIDATION_ERROR" and code(SIM(mode="NONE", probability=1.5)) == "VALIDATION_ERROR")
SIM(mode="NONE")
config.DEBUG_TOOLS = False
chk("DEBUG_TOOLS=0 -> FORBIDDEN (PUT + reset)", code(SIM(mode="NONE")) == "FORBIDDEN" and code(call("POST", "/admin/reset", uid=OFF)) == "FORBIDDEN")
config.DEBUG_TOOLS = True

# 9. reset
db.execute("UPDATE accounts SET balance=1 WHERE account_id=2"); SIM(mode="BEFORE_DEBIT")
chk("reset 200", call("POST", "/admin/reset", uid=OFF)[0] == 200)
OFF = data(call("POST", "/auth/login", {"username": "officer", "password": "officer123"}))["user"]["user_id"]  # default seed ids differ
dl = call("POST", "/auth/login", {"username": "demo", "password": "demo123"})
chk("reset restores the single demo customer + officer, sim NONE", data(dl)["accounts"][0]["balance"] == "10000.00"
    and data(call("GET", "/admin/simulation", uid=OFF))["mode"] == "NONE"
    and all(code(call("POST", "/auth/login", {"username": u, "password": u + "123"})) == "INVALID_CREDENTIALS" for u in ("alice", "bob", "carol")))
chk("demo customer is the only customer", len(data(call("GET", "/admin/customers", uid=OFF))["customers"]) == 1)
chk("reset removed new users", code(call("POST", "/auth/login", {"username": "dave", "password": "dave1234"})) == "INVALID_CREDENTIALS")
chk("final integrity ok", integ()["ok"] is True)
chk("no password hash in any response", not any(k in s for s in SEEN for k in ("password_hash", "pbkdf2:", "scrypt:")))
init_db.reset_database(test_fixtures=True)  # leave the DB in the fixture state the other selfchecks expect
print(f"\n{'ALL PASS' if not FAILS else 'FAILED: ' + '; '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
