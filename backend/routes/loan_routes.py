from flask import Blueprint, request

from middleware import require_user
from responses import ok
from services import loan_service as S
from flask import g

loan_bp = Blueprint("loan_bp", __name__)
_b = lambda: request.get_json(silent=True) or {}


@loan_bp.get("/config")
@require_user
def config_(): return ok(S.config_())


@loan_bp.get("/estimate")
@require_user
def estimate(): return ok(S.estimate(request.args))


@loan_bp.post("")
@require_user
def create(): return ok(S.create(g.user_id, _b()), 201)


@loan_bp.get("")
@require_user
def list_(): return ok(S.list_loans(g.user_id, request.args.get("status") or None))


@loan_bp.get("/<int:loan_id>")
@require_user
def get(loan_id): return ok(S.get(g.user_id, loan_id))


@loan_bp.put("/<int:loan_id>/details")
@require_user
def details(loan_id): return ok(S.details(g.user_id, loan_id, _b()))


@loan_bp.put("/<int:loan_id>/income-details")
@require_user
def income(loan_id): return ok(S.income_details(g.user_id, loan_id, _b()))


@loan_bp.post("/<int:loan_id>/documents")
@require_user
def document(loan_id):
    return ok(S.upload_document(g.user_id, loan_id, request.form.get("document_type"), request.files.get("file")), 201)


@loan_bp.put("/<int:loan_id>/guarantor")
@require_user
def guarantor(loan_id): return ok(S.guarantor(g.user_id, loan_id, _b()))


@loan_bp.post("/<int:loan_id>/submit")
@require_user
def submit(loan_id): return ok(S.submit(g.user_id, loan_id))


@loan_bp.post("/<int:loan_id>/accept")
@require_user
def accept(loan_id): return ok(S.accept(g.user_id, loan_id, _b()))


@loan_bp.post("/<int:loan_id>/cancel")
@require_user
def cancel(loan_id): return ok(S.cancel(g.user_id, loan_id))


@loan_bp.get("/<int:loan_id>/schedule")
@require_user
def schedule(loan_id): return ok(S.schedule(g.user_id, loan_id))


@loan_bp.post("/<int:loan_id>/repay")
@require_user
def repay(loan_id):
    payload, status = S.repay(g.user_id, loan_id, _b())
    return ok(payload, status)
