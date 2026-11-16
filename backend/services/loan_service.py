"""Personal-loan workflow (design §7.4, §9). Money moves only via ledger.move_money."""
import json, os, uuid
from datetime import date
from decimal import Decimal as D

import mysql.connector

import config, db
from errors import ApiError, SimulatedNetworkError
from money import money_str, parse_money
from services import failure_sim, ledger
from services.loan_engine import build_schedule, calc_emi, evaluate_application
from services.notify import create_notification
from utils import add_months, iso, utcnow, validate_fields

SYSTEM_ACCOUNT_ID = 1
TENURES = [6, 12, 18, 24, 36]
EMP = ["SALARIED", "SELF_EMPLOYED", "BUSINESS", "OTHER"]
REL = ["SPOUSE", "PARENT", "SIBLING", "CHILD", "OTHER_RELATIVE", "FRIEND", "COLLEAGUE"]
DOCS = ["INCOME_PROOF", "PAN_CARD", "AADHAR_CARD"]
MIME = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}
MAX_BYTES = 2 * 1024 * 1024
LMIN, LMAX = "5000.00", "500000.00"
TENURE_RE, PHONE_RE, AADHAR_RE = "6|12|18|24|36", r"\d{10,15}", r"\d{12}"
ST = ["DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED", "ACTIVE", "CLOSED", "CANCELLED"]


# ---------- helpers ----------
def _m(v): return None if v is None else money_str(v)
def _d(v): return None if v is None else v.isoformat()
def _one(cur, sql, p=()): cur.execute(sql, p); return cur.fetchone()
def _all(cur, sql, p=()): cur.execute(sql, p); return cur.fetchall()


def _check(body, rules, money=(), extra=None):
    """validate_fields + parse_money + custom checks, reporting ALL bad fields at once."""
    fields, vals = {}, {}
    try: vals = validate_fields({k: str(v) for k, v in body.items() if v is not None}, rules)
    except ApiError as e: fields.update(e.details.get("fields", {}))
    for name, lo, hi in money:
        try: vals[name] = parse_money(body.get(name), name, lo, hi)
        except ApiError as e: fields.update(e.details.get("fields", {}))
    if extra and not fields: fields.update(extra(vals))
    if fields: raise ApiError("VALIDATION_ERROR", "Invalid input", {"fields": fields})
    return vals


def _get(loan_id, uid, cur=None, lock=False):
    sql = "SELECT * FROM loans WHERE loan_id=%s" + (" FOR UPDATE" if lock else "")
    row = _one(cur, sql, (loan_id,)) if cur else db.fetch_one(sql, (loan_id,))
    if not row: raise ApiError("NOT_FOUND", "Loan not found")
    if row["user_id"] != uid: raise ApiError("FORBIDDEN", "This loan belongs to another user")
    return row


def _mutate(loan_id, uid, allowed, fn, validate=None):
    """ownership -> validation -> (txn: lock loan, state check, fn) -> Loan."""
    _get(loan_id, uid)
    v = validate() if validate else None

    def t(cur):
        loan = _get(loan_id, uid, cur, lock=True)
        if loan["status"] not in allowed:
            raise ApiError("INVALID_STATE", f"Loan is {loan['status']}; allowed only in {', '.join(allowed)}")
        return fn(cur, loan, v)
    db.run_transaction(t)
    return {"loan": _loan(loan_id)}


def _inst(r):
    return {"installment_no": r["installment_no"], "due_date": _d(r["due_date"]), "emi_amount": _m(r["emi_amount"]),
            "principal_component": _m(r["principal_component"]), "interest_component": _m(r["interest_component"]),
            "balance_after": _m(r["balance_after"]), "status": r["status"],
            "is_overdue": r["status"] == "PENDING" and r["due_date"] < utcnow().date(), "paid_at": iso(r["paid_at"])}


def _installments(loan_id):
    return [_inst(r) for r in db.fetch_all(
        "SELECT * FROM repayment_schedule WHERE loan_id=%s ORDER BY installment_no", (loan_id,))]


def _loan(loan_id):
    """THE Loan serializer (§6) — used by every endpoint."""
    l = db.fetch_one(
        "SELECT l.*, a.account_number, (SELECT COUNT(*) FROM repayment_schedule s "
        "WHERE s.loan_id=l.loan_id AND s.status='PAID') AS paid FROM loans l "
        "JOIN accounts a ON a.account_id=l.account_id WHERE l.loan_id=%s", (loan_id,))
    docs = db.fetch_all("SELECT document_type, original_filename, uploaded_at FROM loan_documents "
                        "WHERE loan_id=%s ORDER BY document_id", (loan_id,))
    g = db.fetch_one("SELECT * FROM guarantors WHERE loan_id=%s", (loan_id,))
    rb = l["rate_breakdown"]
    rb = json.loads(rb) if isinstance(rb, (str, bytes)) else rb
    step = (5 if l["status"] != "DRAFT" else 2 if l["applicant_name"] is None
            else 3 if l["pan_number"] is None or len(docs) < 3 else 4)
    return {
        "loan_id": l["loan_id"], "loan_type": l["loan_type"], "status": l["status"], "current_step": step,
        "account_number": l["account_number"], "requested_amount": _m(l["requested_amount"]),
        "tenure_months": l["tenure_months"], "approved_amount": _m(l["approved_amount"]),
        "interest_rate": _m(l["interest_rate"]), "emi_amount": _m(l["emi_amount"]),
        "total_interest": _m(l["total_interest"]), "total_payable": _m(l["total_payable"]),
        "personal_details": None if l["applicant_name"] is None else {
            "full_name": l["applicant_name"], "phone": l["applicant_phone"],
            "address": l["applicant_address"], "date_of_birth": _d(l["applicant_dob"])},
        "income_details": None if l["pan_number"] is None else {
            "pan_number": l["pan_number"], "aadhar_number": l["aadhar_number"],
            "employment_type": l["employment_type"], "monthly_income": _m(l["monthly_income"])},
        "documents": [{"document_type": d["document_type"], "original_filename": d["original_filename"],
                       "uploaded_at": iso(d["uploaded_at"])} for d in docs],
        "guarantor": None if not g else {
            "guarantor_name": g["guarantor_name"], "guarantor_aadhar": g["guarantor_aadhar"],
            "guarantor_phone": g["guarantor_phone"], "relationship": g["relationship"]},
        "review": {"mode": l["review_mode"], "remarks": l["review_remarks"],
                   "rejection_codes": [c for c in (l["rejection_codes"] or "").split(",") if c],
                   "rate_breakdown": rb, "reviewed_at": iso(l["reviewed_at"])},
        "installments_paid": l["paid"],
        "installments_total": l["tenure_months"] if l["status"] in ("ACTIVE", "CLOSED") else 0,
        "submitted_at": iso(l["submitted_at"]), "disbursed_at": iso(l["disbursed_at"]),
        "closed_at": iso(l["closed_at"]), "created_at": iso(l["created_at"])}


# ---------- config / estimate ----------
def config_():
    types = [("PERSONAL", "Personal", True), ("PROFESSIONAL", "Professional", False), ("GOLD", "Gold", False),
             ("CAR", "Car", False), ("HOME", "Home", False)]
    return {"loan_types": [{"code": c, "label": l, "enabled": e} for c, l, e in types],
            "min_amount": LMIN, "max_amount": LMAX, "tenure_options": TENURES,
            "base_rate": "9.00", "best_rate": "5.00", "employment_types": EMP, "relationships": REL,
            "document_types": DOCS, "max_upload_bytes": MAX_BYTES, "allowed_mime_types": list(MIME)}


def estimate(args):
    a = {k: v for k, v in args.items() if v not in (None, "")}
    a.setdefault("rate", "9.00")
    v = _check(a, {"tenure_months": {"regex": TENURE_RE, "msg": "must be one of 6,12,18,24,36"}},
               [("amount", LMIN, LMAX), ("rate", "0.00", "50.00")])
    n, rows = int(v["tenure_months"]), None
    rows = build_schedule(v["amount"], v["rate"], n, date.today())
    payable = sum(r["emi_amount"] for r in rows)
    return {"amount": _m(v["amount"]), "tenure_months": n, "annual_rate": _m(v["rate"]),
            "emi_amount": _m(calc_emi(v["amount"], v["rate"], n)),
            "total_interest": _m(payable - v["amount"]), "total_payable": _m(payable)}


# ---------- application steps ----------
def create(uid, body):
    v = _check(body, {"loan_type": {"choices": ["PERSONAL"], "msg": "only PERSONAL is available"},
                      "account_number": {"regex": AADHAR_RE, "msg": "must be 12 digits"}})
    a = db.fetch_one("SELECT account_id, user_id, status FROM accounts WHERE account_number=%s",
                     (v["account_number"],))
    if not a: raise ApiError("ACCOUNT_NOT_FOUND", "Account not found")
    if a["user_id"] != uid: raise ApiError("FORBIDDEN", "Account is not yours")
    if a["status"] != "ACTIVE": raise ApiError("ACCOUNT_NOT_ACTIVE", "Account is not active")
    return {"loan": _loan(db.execute("INSERT INTO loans (user_id, account_id) VALUES (%s,%s)", (uid, a["account_id"])))}


def list_loans(uid, status=None):
    if status and status not in ST:
        raise ApiError("VALIDATION_ERROR", "Invalid status", {"fields": {"status": "unknown status"}})
    rows = db.fetch_all(
        "SELECT l.*, (SELECT COUNT(*) FROM repayment_schedule s WHERE s.loan_id=l.loan_id AND s.status='PAID') AS paid, "
        "(SELECT MIN(due_date) FROM repayment_schedule s WHERE s.loan_id=l.loan_id AND s.status='PENDING') AS nxt "
        "FROM loans l WHERE l.user_id=%s" + (" AND l.status=%s" if status else "") + " ORDER BY l.loan_id DESC",
        (uid, status) if status else (uid,))
    return {"loans": [{
        "loan_id": r["loan_id"], "loan_type": r["loan_type"], "status": r["status"],
        "requested_amount": _m(r["requested_amount"]), "approved_amount": _m(r["approved_amount"]),
        "interest_rate": _m(r["interest_rate"]), "emi_amount": _m(r["emi_amount"]),
        "tenure_months": r["tenure_months"], "installments_paid": r["paid"],
        "installments_total": r["tenure_months"] if r["status"] in ("ACTIVE", "CLOSED") else 0,
        "next_due_date": _d(r["nxt"]), "created_at": iso(r["created_at"])} for r in rows]}


def get(uid, loan_id):
    _get(loan_id, uid)
    return {"loan": _loan(loan_id)}


def _dob_extra(v):
    try: dob = date.fromisoformat(v["date_of_birth"])
    except ValueError: return {"date_of_birth": "must be YYYY-MM-DD"}
    t = utcnow().date()
    age = t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))
    return {"date_of_birth": "applicant must be at least 21 years old"} if age < 21 else {}


def details(uid, loan_id, body):
    v = lambda: _check(body, {
        "full_name": {"max_len": 100}, "phone": {"regex": PHONE_RE, "msg": "10-15 digits"},
        "address": {"max_len": 255}, "date_of_birth": {"regex": r"\d{4}-\d{2}-\d{2}", "msg": "must be YYYY-MM-DD"},
        "tenure_months": {"regex": TENURE_RE, "msg": "must be one of 6,12,18,24,36"}},
        [("requested_amount", LMIN, LMAX)], _dob_extra)
    return _mutate(loan_id, uid, ["DRAFT"], lambda cur, l, x: cur.execute(
        "UPDATE loans SET applicant_name=%s, applicant_phone=%s, applicant_address=%s, applicant_dob=%s, "
        "requested_amount=%s, tenure_months=%s WHERE loan_id=%s",
        (x["full_name"], x["phone"], x["address"], x["date_of_birth"], x["requested_amount"],
         int(x["tenure_months"]), loan_id)), v)


def income_details(uid, loan_id, body):
    v = lambda: _check(body, {"pan_number": {"regex": r"[A-Z]{5}[0-9]{4}[A-Z]", "msg": "invalid PAN"},
                              "aadhar_number": {"regex": AADHAR_RE, "msg": "must be 12 digits"},
                              "employment_type": {"choices": EMP}},
                       [("monthly_income", "0.01", "1000000000.00")])
    return _mutate(loan_id, uid, ["DRAFT"], lambda cur, l, x: cur.execute(
        "UPDATE loans SET pan_number=%s, aadhar_number=%s, employment_type=%s, monthly_income=%s WHERE loan_id=%s",
        (x["pan_number"], x["aadhar_number"], x["employment_type"], x["monthly_income"], loan_id)), v)


def guarantor(uid, loan_id, body):
    v = lambda: _check(body, {"guarantor_name": {"max_len": 100},
                              "guarantor_aadhar": {"regex": AADHAR_RE, "msg": "must be 12 digits"},
                              "guarantor_phone": {"required": False, "regex": PHONE_RE, "msg": "10-15 digits"},
                              "relationship": {"choices": REL}})
    return _mutate(loan_id, uid, ["DRAFT"], lambda cur, l, x: cur.execute(
        "INSERT INTO guarantors (loan_id, guarantor_name, guarantor_aadhar, guarantor_phone, relationship) "
        "VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE guarantor_name=VALUES(guarantor_name), "
        "guarantor_aadhar=VALUES(guarantor_aadhar), guarantor_phone=VALUES(guarantor_phone), "
        "relationship=VALUES(relationship)",
        (loan_id, x["guarantor_name"], x["guarantor_aadhar"], x.get("guarantor_phone"), x["relationship"])), v)


def upload_document(uid, loan_id, doc_type, f):
    _get(loan_id, uid)
    data = f.read(MAX_BYTES + 1) if f else b""
    err = {}
    if doc_type not in DOCS: err["document_type"] = f"must be one of {', '.join(DOCS)}"
    if not f or not data: err["file"] = "a non-empty file is required"
    elif f.mimetype not in MIME: err["file"] = "only PDF, PNG or JPEG allowed"
    elif len(data) > MAX_BYTES: err["file"] = "file larger than 2 MB"
    if err: raise ApiError("VALIDATION_ERROR", "Invalid upload", {"fields": err})
    folder = os.path.join(config.UPLOAD_DIR, f"loan_{loan_id}")
    path = os.path.join(folder, f"{doc_type}_{uuid.uuid4().hex}{MIME[f.mimetype]}")
    os.makedirs(folder, exist_ok=True)
    with open(path, "wb") as fh: fh.write(data)
    old = []

    def save(cur, l, _):
        old[:] = [r["stored_path"] for r in _all(cur, "SELECT stored_path FROM loan_documents "
                                                 "WHERE loan_id=%s AND document_type=%s", (loan_id, doc_type))]
        cur.execute("DELETE FROM loan_documents WHERE loan_id=%s AND document_type=%s", (loan_id, doc_type))
        cur.execute("INSERT INTO loan_documents (loan_id, document_type, original_filename, stored_path, "
                    "mime_type, size_bytes) VALUES (%s,%s,%s,%s,%s,%s)",
                    (loan_id, doc_type, (f.filename or "upload")[:255], path, f.mimetype, len(data)))
    try: out = _mutate(loan_id, uid, ["DRAFT"], save)
    except Exception:
        os.remove(path); raise
    for p in old:
        try: os.remove(p)
        except OSError: pass
    d = next(x for x in out["loan"]["documents"] if x["document_type"] == doc_type)
    return {"document": d, "loan": out["loan"]}


def submit(uid, loan_id):
    def go(cur, l, _):
        have = {r["document_type"] for r in _all(cur, "SELECT document_type FROM loan_documents WHERE loan_id=%s", (loan_id,))}
        missing = (["details"] if l["applicant_name"] is None else []) + \
                  (["income_details"] if l["pan_number"] is None else []) + \
                  [f"documents:{t}" for t in DOCS if t not in have] + \
                  ([] if _one(cur, "SELECT 1 x FROM guarantors WHERE loan_id=%s", (loan_id,)) else ["guarantor"])
        if missing: raise ApiError("LOAN_INCOMPLETE", "Application is incomplete", {"missing": missing})
        cur.execute("UPDATE loans SET status='PENDING_REVIEW', submitted_at=UTC_TIMESTAMP() WHERE loan_id=%s", (loan_id,))
        create_notification(cur, uid, "LOAN_SUBMITTED", "Loan submitted",
                            f"Your loan application #{loan_id} is under review.", loan_id)
    return _mutate(loan_id, uid, ["DRAFT"], go)


def review(uid, loan_id, body):
    v = lambda: _check(body, {"decision": {"choices": ["AUTO", "APPROVE", "REJECT"]},
                              "remarks": {"required": False, "max_len": 255}})

    def go(cur, l, x):
        g = _one(cur, "SELECT * FROM guarantors WHERE loan_id=%s", (loan_id,))
        c = _one(cur, "SELECT COALESCE(SUM(status='ACTIVE'),0) act, COALESCE(SUM(status='CLOSED'),0) done "
                      "FROM loans WHERE user_id=%s", (uid,))
        ev = evaluate_application(l, g, int(c["act"]), int(c["done"]) > 0)
        mode = x["decision"]
        approved = ev["decision"] == "APPROVE" if mode == "AUTO" else mode == "APPROVE"
        codes = ev["rejection_codes"] if mode == "AUTO" else [] if approved else ["MANUAL_REJECTION"]
        amt, n, rate = l["requested_amount"], l["tenure_months"], ev["interest_rate"]
        payable = sum(r["emi_amount"] for r in build_schedule(amt, rate, n, utcnow().date()))
        cur.execute(
            "UPDATE loans SET status=%s, review_mode=%s, review_remarks=%s, rejection_codes=%s, rate_breakdown=%s, "
            "interest_rate=%s, emi_amount=%s, total_interest=%s, total_payable=%s, approved_amount=%s, "
            "reviewed_at=UTC_TIMESTAMP() WHERE loan_id=%s",
            ("APPROVED" if approved else "REJECTED", mode, x.get("remarks"), ",".join(codes) or None,
             json.dumps(ev["rate_breakdown"]), rate, calc_emi(amt, rate, n), payable - amt, payable,
             amt if approved else None, loan_id))
        if approved:
            create_notification(cur, uid, "LOAN_APPROVED", "Loan approved",
                                f"Loan #{loan_id} approved at {rate}% p.a. Accept it to receive ₹{amt:,.2f}.", loan_id)
        else:
            create_notification(cur, uid, "LOAN_REJECTED", "Loan rejected",
                                f"Loan #{loan_id} was rejected: {', '.join(codes)}.", loan_id)
    return _mutate(loan_id, uid, ["PENDING_REVIEW"], go, v)


def _owner(loan_id):
    row = db.fetch_one("SELECT user_id FROM loans WHERE loan_id=%s", (loan_id,))
    if not row: raise ApiError("NOT_FOUND", "Loan not found")
    return row["user_id"]


def officer_review(loan_id, body):
    """Loan-officer decision on someone else's PENDING_REVIEW loan (same rules/notifications as review())."""
    return review(_owner(loan_id), loan_id, body)


def officer_get(loan_id):
    _owner(loan_id)
    return {"loan": _loan(loan_id)}


def officer_list(status=None):
    if status and status not in ST:
        raise ApiError("VALIDATION_ERROR", "Invalid status", {"fields": {"status": "unknown status"}})
    rows = db.fetch_all(
        "SELECT l.loan_id, l.status, l.requested_amount, l.approved_amount, l.interest_rate, l.tenure_months, "
        "l.created_at, l.submitted_at, u.username, u.full_name FROM loans l JOIN users u ON u.user_id=l.user_id"
        + (" WHERE l.status=%s" if status else "") + " ORDER BY l.loan_id DESC LIMIT 100", (status,) if status else ())
    return {"loans": [{"loan_id": r["loan_id"], "status": r["status"], "customer": r["full_name"], "username": r["username"],
                       "requested_amount": _m(r["requested_amount"]), "approved_amount": _m(r["approved_amount"]),
                       "interest_rate": _m(r["interest_rate"]), "tenure_months": r["tenure_months"],
                       "submitted_at": iso(r["submitted_at"]), "created_at": iso(r["created_at"])} for r in rows]}


def cancel(uid, loan_id):
    return _mutate(loan_id, uid, ["DRAFT", "PENDING_REVIEW", "APPROVED"], lambda cur, l, _: cur.execute(
        "UPDATE loans SET status='CANCELLED' WHERE loan_id=%s", (loan_id,)))


def schedule(uid, loan_id):
    _get(loan_id, uid)
    rows = db.fetch_all("SELECT * FROM repayment_schedule WHERE loan_id=%s ORDER BY installment_no", (loan_id,))
    pend = [r for r in rows if r["status"] == "PENDING"]
    paid = [r for r in rows if r["status"] == "PAID"]
    s = lambda rs, k: sum((r[k] for r in rs), D("0.00"))
    return {"loan_id": loan_id, "schedule": [_inst(r) for r in rows],
            "summary": {"paid_count": len(paid), "total_count": len(rows),
                        "outstanding_principal": _m(s(pend, "principal_component")),
                        "total_paid": _m(s(paid, "emi_amount")), "total_remaining": _m(s(pend, "emi_amount"))}}


# ---------- money operations: accept + repay ----------
class _Replay(Exception):
    def __init__(self, txn): self.txn = txn


def _replay_check(cur, key, uid):
    t = ledger.find_by_idempotency_key(cur, key, uid) if key else None
    if t: raise _Replay(t)


def _find(key, uid):
    with db.transaction() as cur:
        return ledger.find_by_idempotency_key(cur, key, uid)


def _money_op(uid, key, mode, ctx, work):
    """idempotency pre-check -> txn -> 1062 backstop -> FAILED row (§8.6) -> drop-response. Returns (txn_ref, replay)."""
    try:
        t = _find(key, uid) if key else None
        if t: return t["txn_ref"], True
        try:
            ref = db.run_transaction(work)
        except _Replay as r:
            return r.txn["txn_ref"], True
        except mysql.connector.IntegrityError as e:
            if e.errno != 1062 or not key: raise
            t = _find(key, uid)
            if t: return t["txn_ref"], True
            raise ApiError("VALIDATION_ERROR", "idempotency_key already used",
                           {"fields": {"idempotency_key": "already used"}})
    except Exception as e:
        code = (e.code if isinstance(e, ApiError) else
                "SIMULATED_NETWORK_FAILURE" if isinstance(e, SimulatedNetworkError) else "INTERNAL_ERROR")
        if "amount" in ctx and code != "VALIDATION_ERROR":   # a money attempt was actually made
            ledger.record_failed_txn(failure_code=code, failure_reason=getattr(e, "message", str(e)), **ctx)
        raise
    failure_sim.maybe_drop_response(mode)   # after commit: 504, money moved, retry replays
    return ref, False


def _key(body):
    v = _check(body, {"idempotency_key": {"required": False, "regex": r"[A-Za-z0-9_-]{8,64}", "msg": "8-64 chars [A-Za-z0-9_-]"}})
    return v.get("idempotency_key")


def accept(uid, loan_id, body):
    _get(loan_id, uid)
    key, mode = _key(body), failure_sim.resolve_mode(None)
    ctx = {"txn_type": "LOAN_DISBURSEMENT", "from_account_id": SYSTEM_ACCOUNT_ID, "loan_id": loan_id, "initiated_by": uid}

    def work(cur):
        l = _get(loan_id, uid, cur, lock=True)                      # lock order: loan -> accounts
        _replay_check(cur, key, uid)
        if l["status"] != "APPROVED":
            raise ApiError("INVALID_STATE", f"Loan is {l['status']}; only APPROVED loans can be accepted")
        ctx.update(amount=l["approved_amount"], to_account_id=l["account_id"])
        r = ledger.move_money(cur, txn_type="LOAN_DISBURSEMENT", from_account_id=SYSTEM_ACCOUNT_ID,
                              to_account_id=l["account_id"], amount=l["approved_amount"],
                              description=f"Loan #{loan_id} disbursement", loan_id=loan_id,
                              idempotency_key=key, initiated_by=uid, simulate_failure=mode)
        rows = build_schedule(l["approved_amount"], l["interest_rate"], l["tenure_months"],
                              add_months(utcnow().date(), 1))
        cur.executemany(
            "INSERT INTO repayment_schedule (loan_id, installment_no, due_date, emi_amount, principal_component, "
            "interest_component, balance_after) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            [(loan_id, r_["installment_no"], r_["due_date"], r_["emi_amount"], r_["principal_component"],
              r_["interest_component"], r_["balance_after"]) for r_ in rows])
        cur.execute("UPDATE loans SET status='ACTIVE', disbursed_at=UTC_TIMESTAMP() WHERE loan_id=%s", (loan_id,))
        create_notification(cur, uid, "LOAN_DISBURSED", "Loan disbursed",
                            f"₹{l['approved_amount']:,.2f} has been credited to your account.", loan_id)
        return r["txn_ref"]
    ref, _ = _money_op(uid, key, mode, ctx, work)
    return {"loan": _loan(loan_id), "transaction": ledger.get_transaction_dict(ref, uid),
            "schedule": _installments(loan_id)}


def repay(uid, loan_id, body):
    l0 = _get(loan_id, uid)
    key, mode = _key(body), failure_sim.resolve_mode(body.get("simulate_failure") if config.DEBUG_TOOLS else None)
    acct_no = body.get("account_number")
    a = db.fetch_one("SELECT account_id, user_id FROM accounts WHERE " + ("account_number=%s" if acct_no else "account_id=%s"),
                     (acct_no or l0["account_id"],))
    if not a: raise ApiError("ACCOUNT_NOT_FOUND", "Account not found")
    if a["user_id"] != uid: raise ApiError("FORBIDDEN", "Account is not yours")
    ctx = {"txn_type": "LOAN_REPAYMENT", "from_account_id": a["account_id"], "to_account_id": SYSTEM_ACCOUNT_ID,
           "loan_id": loan_id, "initiated_by": uid}

    def work(cur):
        l = _get(loan_id, uid, cur, lock=True)
        _replay_check(cur, key, uid)
        if l["status"] != "ACTIVE":
            raise ApiError("INVALID_STATE", f"Loan is {l['status']}; only ACTIVE loans can be repaid")
        i = _one(cur, "SELECT * FROM repayment_schedule WHERE loan_id=%s AND status='PENDING' "
                      "ORDER BY installment_no LIMIT 1 FOR UPDATE", (loan_id,))
        ctx["amount"] = i["emi_amount"]
        r = ledger.move_money(cur, txn_type="LOAN_REPAYMENT", from_account_id=a["account_id"],
                              to_account_id=SYSTEM_ACCOUNT_ID, amount=i["emi_amount"],
                              description=f"EMI {i['installment_no']}/{l['tenure_months']} for loan #{loan_id}",
                              loan_id=loan_id, idempotency_key=key, initiated_by=uid, simulate_failure=mode)
        cur.execute("UPDATE repayment_schedule SET status='PAID', paid_at=UTC_TIMESTAMP(), paid_txn_id=%s "
                    "WHERE installment_id=%s", (r["txn_id"], i["installment_id"]))
        create_notification(cur, uid, "REPAYMENT_PAID", "EMI paid",
                            f"EMI {i['installment_no']}/{l['tenure_months']} of ₹{i['emi_amount']:,.2f} paid.", loan_id)
        if not _one(cur, "SELECT 1 x FROM repayment_schedule WHERE loan_id=%s AND status='PENDING' LIMIT 1", (loan_id,)):
            cur.execute("UPDATE loans SET status='CLOSED', closed_at=UTC_TIMESTAMP() WHERE loan_id=%s", (loan_id,))
            create_notification(cur, uid, "LOAN_CLOSED", "Loan closed",
                                f"Loan #{loan_id} is fully repaid. Thank you!", loan_id)
        return r["txn_ref"]
    ref, replay = _money_op(uid, key, mode, ctx, work)
    row = db.fetch_one("SELECT s.* FROM repayment_schedule s JOIN transactions t ON t.txn_id=s.paid_txn_id "
                       "WHERE t.txn_ref=%s", (ref,))
    return ({"installment": _inst(row), "transaction": ledger.get_transaction_dict(ref, uid),
             "loan": _loan(loan_id), "idempotent_replay": replay}, 200 if replay else 201)
