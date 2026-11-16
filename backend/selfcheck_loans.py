"""03llm selfcheck. Needs server on :5000 (python backend/app.py) + MySQL. RESETS THE DB. Prints PASS/FAIL per line."""
import json, re, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal as D, ROUND_HALF_UP

import requests

import db, init_db
from services import failure_sim, ledger
from services.health_service import integrity_report
from services.loan_engine import build_schedule, calc_emi, compute_rate, evaluate_application

BASE, FAILS = "http://127.0.0.1:5000/api/loans", []
ACC = {2: "100000000001", 3: "100000000002", 4: "100000000003"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def chk(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {extra}"))
    if not ok: FAILS.append(name)


def call(m, p, uid=2, **kw):
    r = requests.request(m, BASE + p, headers={"X-User-Id": str(uid)}, timeout=60, **kw)
    return r.status_code, r.json()


def review(lid, uid=5, **json):
    """Loan-officer decision (uid 5 = officer in the test fixtures)."""
    r = requests.post(f"http://127.0.0.1:5000/api/admin/loans/{lid}/review", headers={"X-User-Id": str(uid)}, json=json, timeout=60)
    return r.status_code, r.json()


def bal(aid): return db.fetch_one("SELECT balance FROM accounts WHERE account_id=%s", (aid,))["balance"]
def paid(lid): return db.fetch_one("SELECT COUNT(*) c FROM repayment_schedule WHERE loan_id=%s AND status='PAID'", (lid,))["c"]
def code(r): return r[1].get("error", {}).get("code")


def integrity():
    return {k: c["violations"] for k, c in integrity_report()["checks"].items()}


def gate(label):
    bad = {k: v for k, v in integrity().items() if v}
    chk(f"integrity I1-I6 after {label}", not bad, bad)


def mk(uid=2, upto="submit", amount="50000.00", tenure=12, income="60000.00", rel="PARENT", aadhar="123412341234", gaadhar="432143214321"):
    lid = call("POST", "", uid, json={"loan_type": "PERSONAL", "account_number": ACC[uid]})[1]["data"]["loan"]["loan_id"]
    call("PUT", f"/{lid}/details", uid, json={"full_name": "Alice Sharma", "phone": "9876500001", "address": "12 MG Road",
                                              "date_of_birth": "1995-04-12", "requested_amount": amount, "tenure_months": tenure})
    call("PUT", f"/{lid}/income-details", uid, json={"pan_number": "ABCDE1234F", "aadhar_number": aadhar,
                                                     "employment_type": "SALARIED", "monthly_income": income})
    for t in ("INCOME_PROOF", "PAN_CARD", "AADHAR_CARD"):
        call("POST", f"/{lid}/documents", uid, data={"document_type": t}, files={"file": ("d.png", PNG, "image/png")})
    call("PUT", f"/{lid}/guarantor", uid, json={"guarantor_name": "Ravi Sharma", "guarantor_aadhar": gaadhar, "relationship": rel})
    if upto != "draft": call("POST", f"/{lid}/submit", uid)
    if upto in ("approved", "active"): review(lid, decision="AUTO")
    if upto == "active": call("POST", f"/{lid}/accept", uid, json={})
    return lid


# ---- 1. engine vectors (independent recompute) ----
def ref_emi(P, rate, n):
    r = D(str(rate)) / 1200
    return (D(str(P)) * r / (1 - (1 + r) ** -n)).quantize(D("0.01"), ROUND_HALF_UP)


chk("B1 EMI 50000@9%/12 = 4372.57", calc_emi(D(50000), D("9.00"), 12) == D("4372.57"))
chk("B1 EMI 50000@5%/12 = 4280.37", calc_emi(D(50000), D("5.00"), 12) == D("4280.37"))
for P, rate, n in [(5000, "9", 6), (500000, "5", 36), ("123456.78", "7.5", 18), (50000, "9", 24)]:
    s, P = build_schedule(D(str(P)), D(rate), n, date(2026, 10, 28)), D(str(P))
    ds = [r["due_date"] for r in s]
    chk(f"B1 schedule P={P} r={rate} n={n}",
        calc_emi(P, D(rate), n) == ref_emi(P, rate, n) and sum(r["principal_component"] for r in s) == P
        and s[-1]["balance_after"] == D("0.00") and len(s) == n
        and sum(r["emi_amount"] for r in s) == sum(r["principal_component"] + r["interest_component"] for r in s)
        and all(a < b for a, b in zip(ds, ds[1:])) and all((b.year * 12 + b.month) - (a.year * 12 + a.month) == 1 for a, b in zip(ds, ds[1:])))

# ---- 2. rate rules ----
rb = compute_rate(D(60000), D(50000), 12, "PARENT", False)
chk("B2 worked example 5.00 + string breakdown", rb["final_rate"] == "5.00" and all(isinstance(v, str) for v in rb.values())
    and set(rb) == {"base", "income_discount", "guarantor_discount", "tenure_discount", "loyalty_discount", "final_rate"}, rb)
inc = lambda i: compute_rate(D(i), D(50000), 12, "FRIEND", False)["income_discount"]
chk("B2 income tiers (0.20/0.35 boundaries)", (inc("21862.85"), inc("21862.84"), inc("12493.06"), inc("12493.05")) == ("2.00", "1.00", "1.00", "0.00"))
ten = lambda n: compute_rate(D(60000), D(50000), n, "FRIEND", False)["tenure_discount"]
chk("B2 tenure tiers", [ten(n) for n in (6, 12, 18, 24, 36)] == ["1.00", "1.00", "0.50", "0.50", "0.00"])
g_ = {r: compute_rate(D(1), D(50000), 36, r, False)["guarantor_discount"] for r in ("SPOUSE", "PARENT", "SIBLING", "CHILD", "OTHER_RELATIVE", "FRIEND", "COLLEAGUE")}
chk("B2 guarantor tiers (all 7)", list(g_.values()) == ["1.00"] * 4 + ["0.50", "0.00", "0.00"], g_)
chk("B2 loyalty on/off + 5.00 floor", compute_rate(D(1), D(50000), 36, "FRIEND", True)["loyalty_discount"] == "1.00"
    and compute_rate(D(60000), D(50000), 12, "PARENT", True)["final_rate"] == "5.00")

# ---- 3. rejection rules (engine) ----
base = dict(monthly_income="60000", requested_amount="50000", tenure_months=12, aadhar_number="111111111111")
G = dict(guarantor_aadhar="222222222222", relationship="PARENT")
ev = lambda l={}, g={}, act=0: evaluate_application({**base, **l}, {**G, **g}, act, False)
chk("B3 clean approval", ev()["decision"] == "APPROVE" and ev()["rejection_codes"] == [])
chk("B3 LOW_INCOME", ev(dict(monthly_income="9999"))["rejection_codes"] == ["LOW_INCOME"])
chk("B3 EMI_TOO_HIGH", ev(dict(monthly_income="10000", requested_amount="50000", tenure_months=6))["rejection_codes"] == ["EMI_TOO_HIGH"])
# NB: AMOUNT_EXCEEDS_LIMIT can never fire alone: EMI/P >= 3.18% (36 mo @ 9%) => P > 20*income implies ratio > 0.63 => EMI_TOO_HIGH too.
chk("B3 AMOUNT_EXCEEDS_LIMIT (with EMI_TOO_HIGH)", ev(dict(monthly_income="20000", requested_amount="400001", tenure_months=36))["rejection_codes"] == ["EMI_TOO_HIGH", "AMOUNT_EXCEEDS_LIMIT"]
    and "AMOUNT_EXCEEDS_LIMIT" not in ev(dict(monthly_income="20000", requested_amount="400000", tenure_months=36))["rejection_codes"])
chk("B3 TOO_MANY_ACTIVE_LOANS", ev(act=2)["rejection_codes"] == ["TOO_MANY_ACTIVE_LOANS"] and ev(act=1)["decision"] == "APPROVE")
chk("B3 GUARANTOR_SAME_AS_APPLICANT", ev(g=dict(guarantor_aadhar="111111111111"))["rejection_codes"] == ["GUARANTOR_SAME_AS_APPLICANT"])
chk("B3 two codes at once", ev(dict(monthly_income="5000"))["rejection_codes"] == ["LOW_INCOME", "EMI_TOO_HIGH"])

# ---- HTTP from here: clean start ----
init_db.reset_database(test_fixtures=True)
failure_sim.set_global("NONE")
try: requests.get(BASE + "/config", headers={"X-User-Id": "2"}, timeout=5)
except Exception as e: sys.exit(f"server not reachable on :5000 ({e})")

# ---- 11. config / estimate ----
EXP = json.loads('{"loan_types":[{"code":"PERSONAL","label":"Personal","enabled":true},{"code":"PROFESSIONAL","label":"Professional","enabled":false},'
                 '{"code":"GOLD","label":"Gold","enabled":false},{"code":"CAR","label":"Car","enabled":false},{"code":"HOME","label":"Home","enabled":false}],'
                 '"min_amount":"5000.00","max_amount":"500000.00","tenure_options":[6,12,18,24,36],"base_rate":"9.00","best_rate":"5.00",'
                 '"employment_types":["SALARIED","SELF_EMPLOYED","BUSINESS","OTHER"],"relationships":["SPOUSE","PARENT","SIBLING","CHILD","OTHER_RELATIVE","FRIEND","COLLEAGUE"],'
                 '"document_types":["INCOME_PROOF","PAN_CARD","AADHAR_CARD"],"max_upload_bytes":2097152,"allowed_mime_types":["application/pdf","image/png","image/jpeg"]}')
chk("B11 /config verbatim", call("GET", "/config")[1]["data"] == EXP)
e1, e2 = call("GET", "/estimate?amount=50000.00&tenure_months=12&rate=9.00")[1]["data"], call("GET", "/estimate?amount=50000.00&tenure_months=12&rate=5.00")[1]["data"]
chk("B11 /estimate vectors", (e1["emi_amount"], e2["emi_amount"]) == ("4372.57", "4280.37") and e1["annual_rate"] == "9.00"
    and D(e1["total_payable"]) - D(e1["total_interest"]) == 50000, (e1, e2))
chk("B11 /estimate default rate + validation", call("GET", "/estimate?amount=50000&tenure_months=12")[1]["data"]["annual_rate"] == "9.00"
    and code(call("GET", "/estimate?amount=100&tenure_months=7")) == "VALIDATION_ERROR")

# ---- 6. validation ----
lid = call("POST", "", 2, json={"loan_type": "PERSONAL", "account_number": ACC[2]})[1]["data"]["loan"]["loan_id"]
GOOD = {"full_name": "Alice Sharma", "phone": "9876500001", "address": "12 MG Road", "date_of_birth": "1995-04-12", "requested_amount": "50000.00", "tenure_months": 12}
dt = lambda **k: call("PUT", f"/{lid}/details", json={**GOOD, **k})
for f, v in [("requested_amount", "4999.99"), ("requested_amount", "500000.01"), ("tenure_months", 7),
             ("date_of_birth", str(date.today().replace(year=date.today().year - 20)))]:
    r = dt(**{f: v}); chk(f"B6 details {f}={v}", r[0] == 400 and code(r) == "VALIDATION_ERROR" and f in r[1]["error"]["details"]["fields"], r)
r = call("PUT", f"/{lid}/details", json={"full_name": "x"}); chk("B6 details missing fields (all reported)", r[0] == 400 and len(r[1]["error"]["details"]["fields"]) >= 5)
INC = {"pan_number": "ABCDE1234F", "aadhar_number": "123412341234", "employment_type": "SALARIED", "monthly_income": "60000.00"}
for f, v in [("pan_number", "abcde1234f"), ("aadhar_number", "12341234123"), ("employment_type", "NONE")]:
    r = call("PUT", f"/{lid}/income-details", json={**INC, isinstance(f, str) and f: v}); chk(f"B6 income {f}", code(r) == "VALIDATION_ERROR" and f in r[1]["error"]["details"]["fields"], r)
r = call("PUT", f"/{lid}/guarantor", json={"guarantor_name": "R", "guarantor_aadhar": "432143214321", "relationship": "NEIGHBOUR"}); chk("B6 bad relationship", code(r) == "VALIDATION_ERROR")
r = call("POST", f"/{lid}/documents", data={"document_type": "PAN_CARD"}, files={"file": ("a.txt", b"hi", "text/plain")}); chk("B6 wrong mime", code(r) == "VALIDATION_ERROR" and "file" in r[1]["error"]["details"]["fields"])
r = call("POST", f"/{lid}/documents", data={"document_type": "PAN_CARD"}, files={"file": ("a.png", b"0" * 3 * 1024 * 1024, "image/png")}); chk("B6 3 MB file", code(r) == "VALIDATION_ERROR" and "file" in r[1]["error"]["details"]["fields"])
r = call("POST", f"/{lid}/documents", data={"document_type": "PASSPORT"}, files={"file": ("a.png", PNG, "image/png")}); chk("B6 bad document_type", code(r) == "VALIDATION_ERROR")
chk("B6 non-PERSONAL type", code(call("POST", "", json={"loan_type": "HOME", "account_number": ACC[2]})) == "VALIDATION_ERROR")
chk("B6 missing fields on create", code(call("POST", "", json={})) == "VALIDATION_ERROR")
r = call("POST", f"/{lid}/submit"); chk("B6 submit empty -> LOAN_INCOMPLETE tokens", code(r) == "LOAN_INCOMPLETE" and r[1]["error"]["details"]["missing"] ==
    ["details", "income_details", "documents:INCOME_PROOF", "documents:PAN_CARD", "documents:AADHAR_CARD", "guarantor"], r)
call("PUT", f"/{lid}/details", json=GOOD); chk("current_step 3 after details", call("GET", f"/{lid}")[1]["data"]["loan"]["current_step"] == 3)
r = call("POST", "", json={"loan_type": "PERSONAL", "account_number": "999999999999"}); chk("ACCOUNT_NOT_FOUND", code(r) == "ACCOUNT_NOT_FOUND")
r = call("POST", "", json={"loan_type": "PERSONAL", "account_number": ACC[3]}); chk("create on someone else's account -> FORBIDDEN", code(r) == "FORBIDDEN")
call("POST", f"/{lid}/cancel")

# ---- 7. ownership ----
lid = mk(2, "draft")
for m, p, b in [("GET", "", None), ("PUT", "/details", GOOD), ("PUT", "/income-details", INC), ("PUT", "/guarantor", {}), ("POST", "/submit", None),
                ("POST", "/accept", {}), ("POST", "/cancel", None), ("GET", "/schedule", None), ("POST", "/repay", {})]:
    chk(f"B7 bob {m} {p or '/'} -> 403", code(call(m, f"/{lid}{p}", 3, json=b)) == "FORBIDDEN")
chk("B7 customers cannot review (owner or not) -> 403", code(review(lid, uid=3, decision="AUTO")) == "FORBIDDEN" and code(review(lid, uid=2, decision="AUTO")) == "FORBIDDEN")
chk("B7 customer /loans/{id}/review route removed", call("POST", f"/{lid}/review", 2, json={"decision": "AUTO"})[0] in (404, 405))
chk("B7 bob upload -> 403", code(call("POST", f"/{lid}/documents", 3, data={"document_type": "PAN_CARD"}, files={"file": ("a.png", PNG, "image/png")})) == "FORBIDDEN")
chk("B7 unknown loan -> NOT_FOUND", code(call("GET", "/999999")) == "NOT_FOUND" and code(call("POST", "/999999/repay", json={})) == "NOT_FOUND")
chk("list only own loans", all(l["loan_id"] != lid for l in call("GET", "", 3)[1]["data"]["loans"]) and any(l["loan_id"] == lid for l in call("GET", "")[1]["data"]["loans"]))

# ---- 5. state machine ----
chk("B5 doc replace keeps 1 row per type", (call("POST", f"/{lid}/documents", data={"document_type": "PAN_CARD"}, files={"file": ("n.png", PNG, "image/png")})[1]["data"]["loan"]["documents"]
    .__len__() == 3) and db.fetch_one("SELECT COUNT(*) c FROM loan_documents WHERE loan_id=%s", (lid,))["c"] == 3)
call("POST", f"/{lid}/submit")
chk("B5 edit after submit", all(code(x) == "INVALID_STATE" for x in [call("PUT", f"/{lid}/details", json=GOOD), call("PUT", f"/{lid}/income-details", json=INC),
    call("PUT", f"/{lid}/guarantor", json={"guarantor_name": "R", "guarantor_aadhar": "432143214321", "relationship": "PARENT"}),
    call("POST", f"/{lid}/documents", data={"document_type": "PAN_CARD"}, files={"file": ("a.png", PNG, "image/png")}), call("POST", f"/{lid}/submit")]))
chk("B5 accept/repay before approval", code(call("POST", f"/{lid}/accept", json={})) == "INVALID_STATE" and code(call("POST", f"/{lid}/repay", json={})) == "INVALID_STATE")
chk("B5 review bad decision", code(review(lid, decision="MAYBE")) == "VALIDATION_ERROR")
r = review(lid, decision="AUTO"); L = r[1]["data"]["loan"]
chk("B4 review AUTO -> APPROVED 5.00%", L["status"] == "APPROVED" and L["interest_rate"] == "5.00" and L["emi_amount"] == "4280.37" and L["approved_amount"] == "50000.00"
    and L["review"]["rate_breakdown"]["final_rate"] == "5.00" and L["review"]["mode"] == "AUTO", r)
chk("B5 review twice", code(review(lid, decision="AUTO")) == "INVALID_STATE")
chk("B5 repay APPROVED loan", code(call("POST", f"/{lid}/repay", json={})) == "INVALID_STATE")
chk("B5 cancel APPROVED ok", call("POST", f"/{lid}/cancel")[1]["data"]["loan"]["status"] == "CANCELLED" and code(call("POST", f"/{lid}/cancel")) == "INVALID_STATE")
l2 = mk(2, "draft"); chk("B5 cancel DRAFT ok", call("POST", f"/{l2}/cancel")[1]["data"]["loan"]["status"] == "CANCELLED")
l2 = mk(2, "submit"); chk("B5 cancel PENDING_REVIEW ok", call("POST", f"/{l2}/cancel")[1]["data"]["loan"]["status"] == "CANCELLED")
l2 = mk(2, "submit"); r = review(l2, decision="REJECT", remarks="nope")[1]["data"]["loan"]
chk("REJECT -> MANUAL_REJECTION, no approved_amount", r["status"] == "REJECTED" and r["review"]["rejection_codes"] == ["MANUAL_REJECTION"] and r["approved_amount"] is None and r["review"]["remarks"] == "nope")
chk("B5 accept REJECTED / cancel REJECTED", code(call("POST", f"/{l2}/accept", json={})) == "INVALID_STATE" and code(call("POST", f"/{l2}/cancel")) == "INVALID_STATE")
l2 = mk(2, "submit", income="5000.00"); r = review(l2, decision="AUTO")[1]["data"]["loan"]
db_codes = db.fetch_one("SELECT rejection_codes c FROM loans WHERE loan_id=%s", (l2,))["c"]
chk("B3 HTTP two codes stored comma-separated, returned array", r["status"] == "REJECTED" and r["review"]["rejection_codes"] == ["LOW_INCOME", "EMI_TOO_HIGH"] and db_codes == "LOW_INCOME,EMI_TOO_HIGH", (r["review"], db_codes))
l2 = mk(2, "submit", aadhar="432143214321"); r = review(l2, decision="AUTO")[1]["data"]["loan"]
chk("B3 HTTP GUARANTOR_SAME_AS_APPLICANT", r["review"]["rejection_codes"] == ["GUARANTOR_SAME_AS_APPLICANT"])
l2 = mk(2, "submit", income="5000.00"); r = review(l2, decision="APPROVE")[1]["data"]["loan"]
chk("manual APPROVE overrides eligibility", r["status"] == "APPROVED" and r["approved_amount"] == "50000.00")
call("POST", f"/{l2}/cancel")

# ---- 4. happy flow (alice) ----
b0, s0 = bal(2), bal(1)
lid = mk(2, "approved")
r = call("POST", f"/{lid}/accept", json={}); d = r[1]["data"]
chk("B4 accept -> ACTIVE + LOAN_DISBURSEMENT + 12 rows", r[0] == 200 and d["loan"]["status"] == "ACTIVE" and d["transaction"]["txn_type"] == "LOAN_DISBURSEMENT"
    and d["transaction"]["status"] == "COMPLETED" and len(d["schedule"]) == 12 and d["loan"]["installments_total"] == 12 and set(d) == {"loan", "transaction", "schedule"}, r)
chk("B4 balances: alice +50000, system -50000", bal(2) == b0 + 50000 and bal(1) == s0 - 50000)
inst_keys = {"installment_no", "due_date", "emi_amount", "principal_component", "interest_component", "balance_after", "status", "is_overdue", "paid_at"}
chk("contract: installment keys + money strings", all(set(i) == inst_keys and re.fullmatch(r"\d+\.\d{2}", i["emi_amount"]) for i in d["schedule"]))
loan_keys = {"loan_id", "loan_type", "status", "current_step", "account_number", "requested_amount", "tenure_months", "approved_amount", "interest_rate", "emi_amount", "total_interest",
             "total_payable", "personal_details", "income_details", "documents", "guarantor", "review", "installments_paid", "installments_total", "submitted_at", "disbursed_at", "closed_at", "created_at"}
chk("contract: Loan keys", set(d["loan"]) == loan_keys and d["loan"]["current_step"] == 5, set(d["loan"]) ^ loan_keys)
chk("B5 accept twice", code(call("POST", f"/{lid}/accept", json={})) == "INVALID_STATE" and code(call("POST", f"/{lid}/cancel")) == "INVALID_STATE")
chk("B5 review ACTIVE", code(review(lid, decision="AUTO")) == "INVALID_STATE")
sc = call("GET", f"/{lid}/schedule")[1]["data"]; chk("schedule summary (fresh)", sc["summary"] == {"paid_count": 0, "total_count": 12, "outstanding_principal": "50000.00",
    "total_paid": "0.00", "total_remaining": sc["summary"]["total_remaining"]} and sc["summary"]["total_remaining"] == L["total_payable"])
ok_ = True
for k in range(1, 13):
    before = bal(2); r = call("POST", f"/{lid}/repay", json={}); x = r[1]["data"]
    ok_ &= r[0] == 201 and x["installment"]["installment_no"] == k and x["installment"]["status"] == "PAID" and before - bal(2) == D(x["installment"]["emi_amount"]) and x["idempotent_replay"] is False
chk("B4 repay x12 (201, right installment, balance drops by EMI)", ok_)
fin = call("GET", f"/{lid}")[1]["data"]["loan"]
chk("B4 loan CLOSED, closed_at, 12/12", fin["status"] == "CLOSED" and fin["closed_at"] and fin["installments_paid"] == 12)
chk("B4 last EMI absorbs rounding; total paid == total_payable", db.fetch_one("SELECT SUM(emi_amount) s FROM repayment_schedule WHERE loan_id=%s", (lid,))["s"] == D(L["total_payable"])
    and D(call("GET", f"/{lid}/schedule")[1]["data"]["summary"]["total_paid"]) == D(L["total_payable"]))
nt = db.fetch_all("SELECT type FROM notifications WHERE user_id=2 AND related_ref=%s", (str(lid),)); tp = [n["type"] for n in nt]
chk("B4 notifications (SUBMITTED, APPROVED, DISBURSED, 12x PAID, CLOSED)", tp.count("LOAN_SUBMITTED") == 1 and tp.count("LOAN_APPROVED") == 1 and tp.count("LOAN_DISBURSED") == 1
    and tp.count("REPAYMENT_PAID") == 12 and tp.count("LOAN_CLOSED") == 1, tp)
chk("B5 repay CLOSED", code(call("POST", f"/{lid}/repay", json={})) == "INVALID_STATE")
gate("happy flow")

# ---- 8. atomicity + idempotency ----
def snap(lid_):
    return (bal(1), bal(2), db.fetch_one("SELECT status FROM loans WHERE loan_id=%s", (lid_,))["status"], paid(lid_),
            db.fetch_one("SELECT COUNT(*) c FROM repayment_schedule WHERE loan_id=%s", (lid_,))["c"],
            db.fetch_one("SELECT COUNT(*) c FROM ledger_entries")["c"], db.fetch_one("SELECT COUNT(*) c FROM notifications")["c"])


la = mk(2, "approved")
for mode in ("BEFORE_COMMIT", "AFTER_DEBIT", "BEFORE_DEBIT"):
    failure_sim.set_global(mode); s = snap(la); nf = db.fetch_one("SELECT COUNT(*) c FROM transactions WHERE status='FAILED' AND loan_id=%s", (la,))["c"]
    r = call("POST", f"/{la}/accept", json={}); failure_sim.set_global("NONE")
    fr = db.fetch_one("SELECT txn_type, amount, loan_id, failure_code FROM transactions WHERE status='FAILED' AND loan_id=%s ORDER BY txn_id DESC LIMIT 1", (la,))
    chk(f"B8 accept {mode}: 503, nothing changed, FAILED row has loan_id", r[0] == 503 and snap(la) == s and fr and fr["loan_id"] == la and fr["txn_type"] == "LOAN_DISBURSEMENT"
        and db.fetch_one("SELECT COUNT(*) c FROM transactions WHERE status='FAILED' AND loan_id=%s", (la,))["c"] == nf + 1, (r[0], fr))
chk("B8 accept still works after failures", call("POST", f"/{la}/accept", json={})[0] == 200)
for mode in ("BEFORE_COMMIT", "AFTER_DEBIT"):
    s = snap(la); r = call("POST", f"/{la}/repay", json={"simulate_failure": mode})
    fr = db.fetch_one("SELECT txn_type, loan_id FROM transactions WHERE status='FAILED' AND failure_code='SIMULATED_NETWORK_FAILURE' AND loan_id=%s ORDER BY txn_id DESC LIMIT 1", (la,))
    chk(f"B8 repay {mode}: 503, nothing changed, FAILED LOAN_REPAYMENT row w/ loan_id", r[0] == 503 and code(r) == "SIMULATED_NETWORK_FAILURE" and snap(la)[:6] == s[:6]
        and fr["txn_type"] == "LOAN_REPAYMENT", r)
K = "idem-drop-0001"; b = bal(2)
r1 = call("POST", f"/{la}/repay", json={"simulate_failure": "DROP_RESPONSE", "idempotency_key": K})
chk("B8 DROP_RESPONSE -> 504, money moved once", r1[0] == 504 and code(r1) == "NETWORK_TIMEOUT" and paid(la) == 1 and b - bal(2) == D("4280.37"), r1)
r2 = call("POST", f"/{la}/repay", json={"simulate_failure": "DROP_RESPONSE", "idempotency_key": K}); x = r2[1].get("data", {})
chk("B8 retry same key -> 200 replay, installment paid exactly once", r2[0] == 200 and x.get("idempotent_replay") is True and x["installment"]["installment_no"] == 1 and paid(la) == 1 and b - bal(2) == D("4280.37"), r2)
r3 = call("POST", f"/{la}/repay", json={"idempotency_key": "another-key-01"}); chk("B8 new key pays installment 2", r3[0] == 201 and r3[1]["data"]["installment"]["installment_no"] == 2)
chk("B8 bad idempotency_key format", code(call("POST", f"/{la}/repay", json={"idempotency_key": "x"})) == "VALIDATION_ERROR")
r4 = call("POST", f"/{la}/repay", 3, json={"idempotency_key": K}); chk("B8 other user cannot replay my key", code(r4) == "FORBIDDEN")
chk("B7 repay from someone else's account -> FORBIDDEN, unknown -> ACCOUNT_NOT_FOUND", code(call("POST", f"/{la}/repay", json={"account_number": ACC[3]})) == "FORBIDDEN"
    and code(call("POST", f"/{la}/repay", json={"account_number": "999999999999"})) == "ACCOUNT_NOT_FOUND")
gate("atomicity")

# ---- 9. concurrency ----
lc = mk(2, "approved"); call("POST", f"/{lc}/accept", json={}); b = bal(2)
with ThreadPoolExecutor(10) as ex: rs = list(ex.map(lambda _: call("POST", f"/{lc}/repay", json={}), range(10)))
nos = sorted(r[1]["data"]["installment"]["installment_no"] for r in rs if r[0] == 201)
chk("B9 10 parallel repays -> installments 1..10 exactly once", len(nos) == 10 and nos == list(range(1, 11)), [r[0] for r in rs])
chk("B9 total debited == 10 x EMI exactly", b - bal(2) == 10 * D("4280.37") and paid(lc) == 10)
lb = mk(3, "approved"); b = bal(3)
with ThreadPoolExecutor(2) as ex: rs = list(ex.map(lambda _: call("POST", f"/{lb}/accept", 3, json={}), range(2)))
chk("B9 2 parallel accepts -> exactly one disbursement", sorted(r[0] for r in rs) == [200, 409] and bal(3) - b == 50000
    and db.fetch_one("SELECT COUNT(*) c FROM transactions WHERE loan_id=%s AND txn_type='LOAN_DISBURSEMENT' AND status='COMPLETED'", (lb,))["c"] == 1, [r[0] for r in rs])
gate("concurrency")

# ---- 10. insufficient funds ----
def drain(uid, keep):
    amt = bal(uid) - D(keep)
    if amt > 0: db.run_transaction(lambda cur: ledger.move_money(cur, txn_type="TRANSFER", from_account_id=uid, to_account_id=4, amount=amt, description="selfcheck drain", initiated_by=uid))


drain(3, "100.00"); s = snap(lb)
r = call("POST", f"/{lb}/repay", 3, json={}); fr = db.fetch_one("SELECT loan_id, failure_code FROM transactions WHERE status='FAILED' AND txn_type='LOAN_REPAYMENT' AND loan_id=%s", (lb,))
chk("B10 INSUFFICIENT_FUNDS: 422, installment stays PENDING, FAILED row w/ loan_id", r[0] == 422 and code(r) == "INSUFFICIENT_FUNDS" and paid(lb) == 0 and fr and fr["failure_code"] == "INSUFFICIENT_FUNDS" and snap(lb)[5] == s[5], r)
la3 = mk(2, "submit"); review(la3, decision="APPROVE")   # AUTO would reject: alice already has 2 ACTIVE loans
db.execute("UPDATE accounts SET status='FROZEN' WHERE account_id=2")   # test-only state toggle, no balance change
r = call("POST", f"/{lc}/repay", json={}); chk("repay on FROZEN account -> ACCOUNT_NOT_ACTIVE", code(r) == "ACCOUNT_NOT_ACTIVE")
r = call("POST", f"/{la3}/accept", json={}); chk("accept to FROZEN account -> ACCOUNT_NOT_ACTIVE", code(r) == "ACCOUNT_NOT_ACTIVE" and call("GET", f"/{la3}")[1]["data"]["loan"]["status"] == "APPROVED")
chk("create loan on FROZEN account -> ACCOUNT_NOT_ACTIVE", code(call("POST", "", json={"loan_type": "PERSONAL", "account_number": ACC[2]})) == "ACCOUNT_NOT_ACTIVE")
db.execute("UPDATE accounts SET status='ACTIVE' WHERE account_id=2")
gate("negative paths")

print(f"\n{'ALL PASS' if not FAILS else 'FAILURES: ' + str(len(FAILS))}")
for f in FAILS: print("  -", f)
sys.exit(1 if FAILS else 0)
