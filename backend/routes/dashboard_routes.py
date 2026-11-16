"""04llm - /api/dashboard (exactly §7.6)."""
from flask import Blueprint, g

from db import fetch_one
from middleware import require_user
from money import money_str
from responses import ok
from services.transfer_service import list_transactions

dash_bp = Blueprint("dash", __name__)


@dash_bp.get("")
@require_user
def dashboard():
    uid = g.user_id
    u = fetch_one("SELECT user_id, full_name FROM users WHERE user_id=%s", (uid,))
    p = fetch_one("SELECT account_id, account_number, balance FROM accounts "
                  "WHERE user_id=%s AND status='ACTIVE' ORDER BY account_id LIMIT 1", (uid,))
    c = fetch_one("SELECT (SELECT COALESCE(SUM(balance),0) FROM accounts WHERE user_id=%s AND status<>'CLOSED') AS total,"
                  " (SELECT COUNT(*) FROM notifications WHERE user_id=%s AND is_read=0) AS unread,"
                  " (SELECT COUNT(*) FROM loans WHERE user_id=%s AND status='ACTIVE') AS loans", (uid,) * 3)
    n = fetch_one("SELECT l.loan_id, s.installment_no, s.due_date, s.emi_amount FROM repayment_schedule s "
                  "JOIN loans l ON l.loan_id=s.loan_id WHERE l.user_id=%s AND l.status='ACTIVE' AND s.status='PENDING' "
                  "ORDER BY s.due_date, s.loan_id, s.installment_no LIMIT 1", (uid,))
    return ok({
        "user": {"user_id": u["user_id"], "full_name": u["full_name"]},
        "primary_account": p and {"account_id": p["account_id"], "account_number": p["account_number"], "balance": money_str(p["balance"])},
        "total_balance": money_str(c["total"]),
        "recent_transactions": list_transactions(uid, {}, 1, 5)["items"],
        "unread_notifications": c["unread"],
        "active_loans": c["loans"],
        "next_installment": n and {"loan_id": n["loan_id"], "installment_no": n["installment_no"],
                                   "due_date": n["due_date"].isoformat(), "emi_amount": money_str(n["emi_amount"])},
        "promo": {"headline": "5% ONLY.", "subtext": "Personal Loans with competitive rates."},
    })
