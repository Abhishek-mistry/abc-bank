"""/api/admin - loan-officer / testing dashboard. Everything here requires an OFFICER account."""
from flask import Blueprint, request

import config
import init_db
from db import fetch_all, fetch_one
from errors import ApiError
from middleware import require_officer
from money import money_str
from responses import ok
from routes.user_routes import json_body
from services import failure_sim, loan_service
from services.health_service import health_summary, integrity_report
from utils import iso

admin_bp = Blueprint("admin", __name__)


def _debug_only():
    if not config.DEBUG_TOOLS:  # read at call time so tests can flip it
        raise ApiError("FORBIDDEN", "Testing tools are disabled on this server")


def _sim():
    return {**failure_sim.get_global(), "modes": list(failure_sim.MODES), "tools_enabled": config.DEBUG_TOOLS}


@admin_bp.get("/overview")
@require_officer
def overview():
    c = fetch_one("SELECT (SELECT COUNT(*) FROM users WHERE is_system=0 AND role='CUSTOMER') AS customers,"
                  " (SELECT COUNT(*) FROM loans WHERE status='PENDING_REVIEW') AS pending,"
                  " (SELECT COUNT(*) FROM loans WHERE status='ACTIVE') AS active_loans,"
                  " (SELECT COUNT(*) FROM transactions) AS txns")
    return ok({"health": health_summary(), "customers": c["customers"], "pending_loans": c["pending"],
               "active_loans": c["active_loans"], "transactions": c["txns"], "tools_enabled": config.DEBUG_TOOLS})


@admin_bp.get("/integrity")
@require_officer
def integrity():
    return ok(integrity_report())


@admin_bp.get("/simulation")
@require_officer
def get_simulation():
    return ok(_sim())


@admin_bp.put("/simulation")
@require_officer
def put_simulation():
    _debug_only()
    b = json_body()
    failure_sim.set_global(b.get("mode"), b.get("probability"))  # validates mode/probability itself
    return ok(_sim())


@admin_bp.post("/reset")
@require_officer
def reset():
    _debug_only()
    init_db.reset_database()
    return ok({"reset": True})


@admin_bp.get("/customers")
@require_officer
def customers():
    rows = fetch_all("SELECT u.user_id, u.username, u.full_name, u.email, u.phone, u.created_at, a.account_number, a.balance, "
                     "a.status FROM users u LEFT JOIN accounts a ON a.user_id=u.user_id "
                     "WHERE u.is_system=0 AND u.role='CUSTOMER' ORDER BY u.user_id, a.account_id")
    return ok({"customers": [{"user_id": r["user_id"], "username": r["username"], "full_name": r["full_name"],
                              "email": r["email"], "phone": r["phone"], "account_number": r["account_number"],
                              "balance": money_str(r["balance"]) if r["balance"] is not None else None,
                              "account_status": r["status"], "created_at": iso(r["created_at"])} for r in rows]})


@admin_bp.get("/transactions")
@require_officer
def transactions():
    status = request.args.get("status")
    if status and status not in ("COMPLETED", "FAILED", "REVERSED", "PENDING"):
        raise ApiError("VALIDATION_ERROR", "Invalid status", {"fields": {"status": "unknown status"}})
    rows = fetch_all("SELECT t.txn_ref, t.txn_type, t.status, t.amount, t.failure_code, t.created_at, "
                     "fa.account_number AS from_number, ta.account_number AS to_number "
                     "FROM transactions t LEFT JOIN accounts fa ON fa.account_id=t.from_account_id "
                     "LEFT JOIN accounts ta ON ta.account_id=t.to_account_id"
                     + (" WHERE t.status=%s" if status else "") + " ORDER BY t.txn_id DESC LIMIT 50",
                     (status,) if status else ())
    return ok({"transactions": [{"txn_ref": r["txn_ref"], "txn_type": r["txn_type"], "status": r["status"],
                                 "amount": money_str(r["amount"]), "failure_code": r["failure_code"],
                                 "from_account": r["from_number"], "to_account": r["to_number"],
                                 "created_at": iso(r["created_at"])} for r in rows]})


@admin_bp.get("/loans")
@require_officer
def loans():
    return ok(loan_service.officer_list(request.args.get("status") or None))


@admin_bp.get("/loans/<int:loan_id>")
@require_officer
def loan(loan_id):
    return ok(loan_service.officer_get(loan_id))


@admin_bp.post("/loans/<int:loan_id>/review")
@require_officer
def review(loan_id):
    return ok(loan_service.officer_review(loan_id, json_body()))
