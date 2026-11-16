"""Transfer / deposit / reversal / history (§7.3, §8.6-8.9). All balance changes go through ledger.move_money."""
from datetime import datetime, timedelta

from mysql.connector import IntegrityError

import db
from errors import ApiError, SimulatedNetworkError
from money import money_str, parse_money
from responses import paginated
from services import failure_sim
from services.ledger import (_FROM, _SELECT, _inr, _load, _rows, _shape, find_by_idempotency_key,
                             get_transaction_dict, move_money, record_failed_txn)
from services.notify import create_notification
from utils import utcnow, validate_fields

SYSTEM_ACCOUNT_ID = 1
_UNRECORDED = {"VALIDATION_ERROR", "AUTH_REQUIRED", "FORBIDDEN", "NOT_FOUND"}  # no FAILED row (§8.6)
_TYPES = ("TRANSFER", "DEPOSIT", "LOAN_DISBURSEMENT", "LOAN_REPAYMENT", "REVERSAL")
_STATUSES = ("COMPLETED", "FAILED", "REVERSED")
_ACCT = {"regex": r"\d{12}", "msg": "must be exactly 12 digits"}
_COMMON = {"note": {"required": False, "max_len": 100, "msg": "max 100 characters"},
           "idempotency_key": {"required": False, "regex": r"[A-Za-z0-9_-]{8,64}",
                               "msg": "8-64 characters: letters, digits, _ or -"},
           "simulate_failure": {"required": False, "choices": failure_sim.MODES}}


def _clean(data, *account_fields):
    rules = {**_COMMON, **{a: _ACCT for a in account_fields}}
    supplied = {k: v for k, v in data.items() if v is not None}
    return {k: v for k, v in validate_fields(supplied, rules).items() if v}


def _find(cur, number):
    r = _rows(cur, "SELECT account_id, user_id FROM accounts WHERE account_number = %s AND is_system = 0", (number,))
    return r[0] if r else None


def _own(user_id, number):
    a = _find(None, number)
    if not a:
        raise ApiError("ACCOUNT_NOT_FOUND", "Account not found")      # not recorded (§8.6)
    if a["user_id"] != user_id:
        raise ApiError("FORBIDDEN", "Account does not belong to you")
    return a


def _acct(number):
    a = db.fetch_one("SELECT account_number, balance FROM accounts WHERE account_number = %s", (number,))
    return {"account_number": a["account_number"], "balance": money_str(a["balance"])}


def _record_failure(ctx, e):
    if isinstance(e, ApiError):
        code, reason = e.code, e.message
    elif isinstance(e, SimulatedNetworkError):
        code, reason = "SIMULATED_NETWORK_FAILURE", f"Simulated network failure at {e.point}"
    else:
        code, reason = "INTERNAL_ERROR", str(e)
    if ctx and code not in _UNRECORDED:
        record_failed_txn(failure_code=code, failure_reason=reason, **ctx)


def _run(user_id, key, mode, ctx, work):
    """Shared skeleton: idempotency pre-check -> ONE DB transaction -> FAILED row on error -> DROP_RESPONSE.
    `ctx` = record_failed_txn kwargs (work() may complete it). work(cur) -> txn_ref. Returns (txn_ref, replay)."""
    hit = key and find_by_idempotency_key(None, key, user_id)                    # §8.8a
    if hit:
        return hit["txn_ref"], True

    def attempt(cur):
        hit = key and find_by_idempotency_key(cur, key, user_id)                 # §8.8b
        return (hit["txn_ref"], True) if hit else (work(cur), False)

    try:
        try:
            ref, replay = db.run_transaction(attempt)
        except IntegrityError as e:                                              # §8.8c: uq_txn_idem backstop
            if e.errno != 1062 or not key:
                raise
            hit = find_by_idempotency_key(None, key, user_id)
            if not hit:  # key belongs to another user
                raise ApiError("VALIDATION_ERROR", "idempotency_key already used",
                               {"fields": {"idempotency_key": "already used"}})
            ref, replay = hit["txn_ref"], True
    except Exception as e:
        _record_failure(ctx, e)
        raise
    if not replay:
        failure_sim.maybe_drop_response(mode)                                    # after commit
    return ref, replay


def transfer(user_id, from_account_number, to_account_number, amount, note, idempotency_key, simulate_failure):
    f = _clean({"from_account_number": from_account_number, "to_account_number": to_account_number,
                "note": note, "idempotency_key": idempotency_key, "simulate_failure": simulate_failure},
               "from_account_number", "to_account_number")
    amt = parse_money(amount, min_value="1.00", max_value="200000.00")
    src = _own(user_id, f["from_account_number"])
    key, mode = f.get("idempotency_key"), failure_sim.resolve_mode(f.get("simulate_failure"))
    ctx = dict(txn_type="TRANSFER", from_account_id=src["account_id"], to_account_id=None, amount=amt,
               description=f.get("note"), initiated_by=user_id, notify_user_id=user_id)

    def work(cur):
        dst = _find(cur, f["to_account_number"])
        if not dst:
            raise ApiError("ACCOUNT_NOT_FOUND", "Recipient account not found")  # recorded, to_account_id NULL
        ctx["to_account_id"] = dst["account_id"]
        r = move_money(cur, txn_type="TRANSFER", from_account_id=src["account_id"], to_account_id=dst["account_id"],
                       amount=amt, description=f.get("note"), idempotency_key=key, initiated_by=user_id,
                       simulate_failure=mode)
        t = get_transaction_dict(r["txn_ref"], cur=cur)
        create_notification(cur, user_id, "TRANSFER_SENT", "Money sent",
                            f"{_inr(amt)} sent to {t['to_name']}", r["txn_ref"])
        create_notification(cur, dst["user_id"], "TRANSFER_RECEIVED", "Money received",
                            f"{_inr(amt)} received from {t['from_name']}", r["txn_ref"])
        return r["txn_ref"]

    ref, replay = _run(user_id, key, mode, ctx, work)
    return ({"transaction": get_transaction_dict(ref, user_id), "from_account": _acct(f["from_account_number"]),
             "idempotent_replay": replay}, 200 if replay else 201)


def deposit(user_id, account_number, amount, note, idempotency_key, simulate_failure):
    f = _clean({"account_number": account_number, "note": note, "idempotency_key": idempotency_key,
                "simulate_failure": simulate_failure}, "account_number")
    amt = parse_money(amount, min_value="1.00", max_value="100000.00")
    acc = _own(user_id, f["account_number"])
    key, mode = f.get("idempotency_key"), failure_sim.resolve_mode(f.get("simulate_failure"))
    ctx = dict(txn_type="DEPOSIT", from_account_id=SYSTEM_ACCOUNT_ID, to_account_id=acc["account_id"], amount=amt,
               description=f.get("note"), initiated_by=user_id)

    def work(cur):
        r = move_money(cur, txn_type="DEPOSIT", from_account_id=SYSTEM_ACCOUNT_ID, to_account_id=acc["account_id"],
                       amount=amt, description=f.get("note"), idempotency_key=key, initiated_by=user_id,
                       simulate_failure=mode)
        create_notification(cur, user_id, "DEPOSIT", "Deposit received", f"{_inr(amt)} deposited", r["txn_ref"])
        return r["txn_ref"]

    ref, replay = _run(user_id, key, mode, ctx, work)
    return ({"transaction": get_transaction_dict(ref, user_id), "account": _acct(f["account_number"]),
             "idempotent_replay": replay}, 200 if replay else 201)


def reverse(user_id, txn_ref, idempotency_key, simulate_failure):
    f = _clean({"idempotency_key": idempotency_key, "simulate_failure": simulate_failure})
    key, mode = f.get("idempotency_key"), failure_sim.resolve_mode(f.get("simulate_failure"))
    ctx = {}  # filled once the original is known and visible to the user

    def work(cur):
        # §8.3 step 2: lock the ORIGINAL txn row first (OF t: the joined accounts stay unlocked until move_money)
        o = _rows(cur, "SELECT t.*, fa.user_id AS from_user, ta.user_id AS to_user FROM transactions t "
                       "LEFT JOIN accounts fa ON fa.account_id = t.from_account_id "
                       "LEFT JOIN accounts ta ON ta.account_id = t.to_account_id "
                       "WHERE t.txn_ref = %s FOR UPDATE OF t", (txn_ref,))
        if not o:
            raise ApiError("NOT_FOUND", "Transaction not found")
        o = o[0]
        if user_id not in (o["from_user"], o["to_user"]):
            raise ApiError("FORBIDDEN", "Not your transaction")
        ctx.update(txn_type="REVERSAL", from_account_id=o["to_account_id"], to_account_id=o["from_account_id"],
                   amount=o["amount"], description=f"Reversal of {txn_ref}", initiated_by=user_id)
        if ((o["txn_type"], o["status"]) != ("TRANSFER", "COMPLETED")
                or utcnow() - o["completed_at"] > timedelta(hours=24)):
            raise ApiError("TXN_NOT_REVERSIBLE", "Only completed transfers from the last 24 hours can be reversed")
        if o["from_user"] != user_id:
            raise ApiError("FORBIDDEN", "Only the sender can reverse a transfer")
        try:
            r = move_money(cur, txn_type="REVERSAL", from_account_id=o["to_account_id"],
                           to_account_id=o["from_account_id"], amount=o["amount"],
                           description=ctx["description"], related_txn_id=o["txn_id"], idempotency_key=key,
                           initiated_by=user_id, simulate_failure=mode)
        except ApiError as e:
            if e.code == "INSUFFICIENT_FUNDS":  # no details: they would expose the recipient's balance
                raise ApiError("REVERSAL_FUNDS_UNAVAILABLE", "Recipient no longer has enough funds") from e
            raise
        cur.execute("UPDATE transactions SET status = 'REVERSED' WHERE txn_id = %s", (o["txn_id"],))
        amt = _inr(o["amount"])
        create_notification(cur, o["from_user"], "TRANSFER_REVERSED", "Transfer reversed",
                            f"{amt} was returned to your account", r["txn_ref"])
        create_notification(cur, o["to_user"], "TRANSFER_REVERSED", "Transfer reversed",
                            f"{amt} was reversed by the sender", r["txn_ref"])
        return r["txn_ref"]

    ref, replay = _run(user_id, key, mode, ctx, work)
    t = get_transaction_dict(ref, user_id)
    return ({"transaction": t, "original": get_transaction_dict(t["related_txn_ref"], user_id),
             "idempotent_replay": replay}, 200 if replay else 201)


def _day(value, field):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ApiError("VALIDATION_ERROR", f"{field}: must be YYYY-MM-DD",
                       {"fields": {field: "must be YYYY-MM-DD"}}) from None


def list_transactions(user_id, filters, page, page_size):
    q = validate_fields({k: filters[k] for k in ("account_id", "type", "status") if filters.get(k)},
                        {"account_id": {"required": False, "regex": r"\d{1,10}", "msg": "must be an integer"},
                         "type": {"required": False, "choices": _TYPES},
                         "status": {"required": False, "choices": _STATUSES}})
    where, args = ["(fa.user_id = %s OR ta.user_id = %s)"], [user_id, user_id]
    acct = int(q["account_id"]) if "account_id" in q else None
    if acct is not None:
        if not db.fetch_one("SELECT 1 AS x FROM accounts WHERE account_id = %s AND user_id = %s", (acct, user_id)):
            raise ApiError("FORBIDDEN", "Account does not belong to you")
        where.append("(t.from_account_id = %s OR t.to_account_id = %s)")
        args += [acct, acct]
    for column, name in (("t.txn_type", "type"), ("t.status", "status")):
        if name in q:
            where.append(f"{column} = %s")
            args.append(q[name])
    if filters.get("from_date"):
        where.append("t.created_at >= %s")
        args.append(_day(filters["from_date"], "from_date"))
    if filters.get("to_date"):  # inclusive whole day
        where.append("t.created_at < %s")
        args.append(_day(filters["to_date"], "to_date") + timedelta(days=1))
    w = " WHERE " + " AND ".join(where)
    total = db.fetch_one("SELECT COUNT(*) AS n " + _FROM + w, args)["n"]
    rows = db.fetch_all(_SELECT + w + " ORDER BY t.txn_id DESC LIMIT %s OFFSET %s",
                        args + [page_size, (page - 1) * page_size])
    return paginated([_shape(r, user_id, acct) for r in rows], page, page_size, total)


def get_transaction_detail(user_id, txn_ref):
    r = _load(None, txn_ref)
    if user_id not in (r["from_user"], r["to_user"]):
        raise ApiError("FORBIDDEN", "Not your transaction")
    entries = db.fetch_all("SELECT a.account_number, e.entry_type, e.amount, e.balance_after FROM ledger_entries e "
                           "JOIN accounts a ON a.account_id = e.account_id WHERE e.txn_id = %s "
                           "ORDER BY e.entry_id", (r["txn_id"],))
    return {"transaction": _shape(r, user_id),
            "ledger_entries": [{**e, "amount": money_str(e["amount"]),
                                "balance_after": money_str(e["balance_after"])} for e in entries]}
