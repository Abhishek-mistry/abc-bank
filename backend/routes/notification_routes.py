"""04llm - /api/notifications."""
from flask import Blueprint, g, request

from db import execute, fetch_all, fetch_one, transaction
from errors import ApiError
from middleware import get_page_args, require_user
from responses import ok, paginated
from utils import iso

notif_bp = Blueprint("notif", __name__)


def notif_dict(n):
    return {"notification_id": n["notification_id"], "type": n["type"], "title": n["title"], "message": n["message"],
            "related_ref": n["related_ref"], "is_read": bool(n["is_read"]), "created_at": iso(n["created_at"])}


@notif_bp.get("")
@require_user
def list_notifications():
    page, size = get_page_args()
    where = "user_id=%s" + (" AND is_read=0" if request.args.get("unread_only", "false").lower() in ("1", "true", "yes") else "")
    total = fetch_one(f"SELECT COUNT(*) AS n FROM notifications WHERE {where}", (g.user_id,))["n"]
    rows = fetch_all(f"SELECT * FROM notifications WHERE {where} ORDER BY notification_id DESC LIMIT %s OFFSET %s",
                     (g.user_id, size, (page - 1) * size))
    unread = fetch_one("SELECT COUNT(*) AS n FROM notifications WHERE user_id=%s AND is_read=0", (g.user_id,))["n"]
    return ok(paginated([notif_dict(r) for r in rows], page, size, total, unread_count=unread))


@notif_bp.post("/read-all")
@require_user
def read_all():
    with transaction() as cur:
        cur.execute("UPDATE notifications SET is_read=1 WHERE user_id=%s AND is_read=0", (g.user_id,))
        return ok({"updated": cur.rowcount})


@notif_bp.post("/<int:notification_id>/read")
@require_user
def read_one(notification_id):
    n = fetch_one("SELECT * FROM notifications WHERE notification_id=%s", (notification_id,))
    if not n:
        raise ApiError("NOT_FOUND", "Notification not found")
    if n["user_id"] != g.user_id:
        raise ApiError("FORBIDDEN", "Not your notification")
    execute("UPDATE notifications SET is_read=1 WHERE notification_id=%s", (notification_id,))
    return ok({"notification": notif_dict({**n, "is_read": 1})})
