"""Ledger core (§8). The ONLY module that changes account balances. Never commits/rolls back (§8.2)."""
import traceback
from decimal import Decimal

import db
from errors import ApiError
from money import money_str
from services import failure_sim
from services.notify import create_notification
from utils import iso, mask_name, new_ref

# Shared with transfer_service (same package): one SELECT that yields the full §6 Transaction shape.
_FROM = """FROM transactions t
  LEFT JOIN accounts fa ON fa.account_id = t.from_account_id LEFT JOIN users fu ON fu.user_id = fa.user_id
  LEFT JOIN accounts ta ON ta.account_id = t.to_account_id   LEFT JOIN users tu ON tu.user_id = ta.user_id
  LEFT JOIN transactions rt ON rt.txn_id = t.related_txn_id"""
_SELECT = ("SELECT t.*, fa.account_number AS from_number, fa.is_system AS from_sys, fa.user_id AS from_user, "
           "fu.full_name AS from_full, ta.account_number AS to_number, ta.is_system AS to_sys, "
           "ta.user_id AS to_user, tu.full_name AS to_full, rt.txn_ref AS related_ref " + _FROM)


def _rows(cur, sql, params=None):
    """Read on `cur` (inside a txn) or, when cur is None, on a fresh pooled connection."""
    if cur is None:
        return db.fetch_all(sql, params)
    cur.execute(sql, params)
    return cur.fetchall()


def _inr(amount):
    return f"₹{amount:,.2f}"


def _post(cur, txn_id, account_id, entry_type, amount):
    """One balance change + its ledger row. Returns the balance right after the change."""
    sign = "-" if entry_type == "DEBIT" else "+"
    cur.execute(f"UPDATE accounts SET balance = balance {sign} %s WHERE account_id = %s", (amount, account_id))
    balance = _rows(cur, "SELECT balance FROM accounts WHERE account_id = %s", (account_id,))[0]["balance"]
    cur.execute("INSERT INTO ledger_entries (txn_id, account_id, entry_type, amount, balance_after) "
                "VALUES (%s, %s, %s, %s, %s)", (txn_id, account_id, entry_type, amount, balance))
    return balance


def move_money(cur, *, txn_type, from_account_id, to_account_id, amount, description=None, loan_id=None,
               related_txn_id=None, idempotency_key=None, initiated_by=None, simulate_failure=None):
    """§8.5, steps in order. Callers should pass a concrete `simulate_failure` (failure_sim.resolve_mode(),
    resolved BEFORE opening the DB transaction) so no second pooled connection is needed inside it."""
    if not isinstance(amount, Decimal):
        raise TypeError("money must be Decimal")
    mode = failure_sim.resolve_mode(simulate_failure)
    # 1. lock both accounts with ONE ordered statement (§8.3)
    acc = {r["account_id"]: r for r in _rows(
        cur, "SELECT account_id, balance, status, is_system FROM accounts "
             "WHERE account_id IN (%s, %s) ORDER BY account_id FOR UPDATE", (from_account_id, to_account_id))}
    src, dst = acc.get(from_account_id), acc.get(to_account_id)
    # 2. validate
    if not (src and dst):
        raise ApiError("ACCOUNT_NOT_FOUND", "Account not found")
    for role, a in (("Sender", src), ("Recipient", dst)):
        if a["status"] != "ACTIVE":
            raise ApiError("ACCOUNT_NOT_ACTIVE", f"{role} account is {a['status'].lower()}")
    if from_account_id == to_account_id:
        raise ApiError("SAME_ACCOUNT_TRANSFER", "Cannot transfer to the same account")
    if not src["is_system"] and src["balance"] < amount:
        raise ApiError("INSUFFICIENT_FUNDS", "Insufficient funds",
                       {"available": money_str(src["balance"]), "required": money_str(amount)})
    # 3. PENDING transaction row
    ref = new_ref()
    cur.execute("INSERT INTO transactions (txn_ref, idempotency_key, txn_type, from_account_id, to_account_id, "
                "amount, status, description, related_txn_id, loan_id, initiated_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', %s, %s, %s, %s)",
                (ref, idempotency_key, txn_type, from_account_id, to_account_id, amount, description,
                 related_txn_id, loan_id, initiated_by))
    txn_id = cur.lastrowid
    failure_sim.maybe_fail("BEFORE_DEBIT", mode)                                  # 4
    from_after = _post(cur, txn_id, from_account_id, "DEBIT", amount)             # 5
    failure_sim.maybe_fail("AFTER_DEBIT", mode)                                   # 6
    to_after = _post(cur, txn_id, to_account_id, "CREDIT", amount)                # 7
    cur.execute("UPDATE transactions SET status = 'COMPLETED', completed_at = UTC_TIMESTAMP() "
                "WHERE txn_id = %s", (txn_id,))                                   # 8
    failure_sim.maybe_fail("BEFORE_COMMIT", mode)                                 # 9
    return {"txn_id": txn_id, "txn_ref": ref, "from_balance_after": from_after, "to_balance_after": to_after}


def record_failed_txn(*, txn_type, from_account_id, to_account_id, amount, failure_code, failure_reason,
                      description=None, loan_id=None, initiated_by=None, notify_user_id=None):
    """§8.6: own transaction, FAILED row (no key, no ledger rows) [+ TRANSFER_FAILED]. Never raises."""
    try:
        ref = new_ref()
        with db.transaction() as cur:
            cur.execute("INSERT INTO transactions (txn_ref, txn_type, from_account_id, to_account_id, amount, "
                        "status, failure_code, failure_reason, description, loan_id, initiated_by) "
                        "VALUES (%s, %s, %s, %s, %s, 'FAILED', %s, %s, %s, %s, %s)",
                        (ref, txn_type, from_account_id, to_account_id, amount, failure_code[:40],
                         failure_reason[:255], description, loan_id, initiated_by))
            if notify_user_id:
                create_notification(cur, notify_user_id, "TRANSFER_FAILED", "Transfer failed",
                                    f"{_inr(amount)} transfer failed: {failure_reason}", ref)
        return ref
    except Exception:
        traceback.print_exc()
        return None


def _party(number, is_sys, full_name):
    if number is None:
        return None, None
    return number, "ABC Bank" if is_sys else mask_name(full_name)


def _shape(r, viewer=None, account_id=None):
    """Joined row (see _SELECT) -> §6 Transaction."""
    from_no, from_name = _party(r["from_number"], r["from_sys"], r["from_full"])
    to_no, to_name = _party(r["to_number"], r["to_sys"], r["to_full"])
    if account_id is not None:
        direction = "OUT" if r["from_account_id"] == account_id else "IN"
    elif viewer is not None:
        direction = "OUT" if r["from_user"] == viewer else "IN"
    else:
        direction = None
    return {"txn_ref": r["txn_ref"], "txn_type": r["txn_type"], "status": r["status"],
            "amount": money_str(r["amount"]), "from_account_number": from_no, "from_name": from_name,
            "to_account_number": to_no, "to_name": to_name, "description": r["description"],
            "direction": direction, "failure_code": r["failure_code"], "failure_reason": r["failure_reason"],
            "related_txn_ref": r["related_ref"], "loan_id": r["loan_id"],
            "created_at": iso(r["created_at"]), "completed_at": iso(r["completed_at"])}


def _load(cur, txn_ref):
    rows = _rows(cur, _SELECT + " WHERE t.txn_ref = %s", (txn_ref,))
    if not rows:
        raise ApiError("NOT_FOUND", "Transaction not found")
    return rows[0]


def get_transaction_dict(txn_ref, viewer_user_id=None, cur=None, account_id=None):
    return _shape(_load(cur, txn_ref), viewer_user_id, account_id)


def find_by_idempotency_key(cur, key, user_id):
    """Replay lookup (§8.8). `cur=None` reads on a fresh connection (used for the pre-check)."""
    rows = _rows(cur, "SELECT txn_ref FROM transactions WHERE idempotency_key = %s AND initiated_by = %s "
                      "AND status IN ('COMPLETED', 'REVERSED')", (key, user_id))
    return get_transaction_dict(rows[0]["txn_ref"], user_id, cur) if rows else None
