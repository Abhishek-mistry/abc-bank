from flask import jsonify


def ok(data, status=200):
    resp = jsonify({"success": True, "data": data})
    resp.status_code = status
    return resp


def paginated(items, page, page_size, total_items, **extra):
    return {"items": items, "page": page, "page_size": page_size, "total_items": total_items,
            "total_pages": -(-total_items // page_size), **extra}
