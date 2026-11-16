"""04llm - /api/system (public liveness only; testing tools live in /api/admin)."""
from flask import Blueprint

from responses import ok
from services.health_service import health_summary
from utils import iso, utcnow

system_bp = Blueprint("system", __name__)


@system_bp.get("/health")
def health():
    h = health_summary()
    return ok({"status": "DEGRADED" if h["status"] == "DEGRADED" else "ALL_GOOD", "db": h["db"],
               "server_time": iso(utcnow())})
