"""Thin HTTP layer for §7.3. url_prefix (/api/transactions) is applied by app.py."""
import config
from flask import Blueprint, g, request

from errors import ApiError
from middleware import get_page_args, require_user
from responses import ok
from services import transfer_service as svc

txn_bp = Blueprint("txn", __name__)


def _sim(b):
    """Per-request failure injection is a testing feature: ignored unless DEBUG_TOOLS is on."""
    return b.get("simulate_failure") if config.DEBUG_TOOLS else None


def _body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError("VALIDATION_ERROR", "A JSON object body is required",
                       {"fields": {"body": "must be a JSON object"}})
    return body


@txn_bp.post("/transfer")
@require_user
def transfer():
    b = _body()
    return ok(*svc.transfer(g.user_id, b.get("from_account_number"), b.get("to_account_number"), b.get("amount"),
                            b.get("note"), b.get("idempotency_key"), _sim(b)))


@txn_bp.post("/deposit")
@require_user
def deposit():
    b = _body()
    return ok(*svc.deposit(g.user_id, b.get("account_number"), b.get("amount"), b.get("note"),
                           b.get("idempotency_key"), _sim(b)))


@txn_bp.post("/<txn_ref>/reverse")
@require_user
def reverse(txn_ref):
    b = _body()
    return ok(*svc.reverse(g.user_id, txn_ref, b.get("idempotency_key"), _sim(b)))


@txn_bp.get("")
@require_user
def list_():
    page, page_size = get_page_args()
    filters = {k: request.args.get(k) for k in ("account_id", "type", "status", "from_date", "to_date")}
    return ok(svc.list_transactions(g.user_id, filters, page, page_size))


@txn_bp.get("/<txn_ref>")
@require_user
def detail(txn_ref):
    return ok(svc.get_transaction_detail(g.user_id, txn_ref))
