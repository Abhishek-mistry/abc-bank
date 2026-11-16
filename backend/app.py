import importlib
import logging

from flask import Flask, request
from werkzeug.exceptions import MethodNotAllowed, NotFound

import config
from errors import register_error_handlers

BLUEPRINTS = [("routes.auth_routes", "auth_bp", "/api/auth"), ("routes.user_routes", "user_bp", "/api/users"),
              ("routes.account_routes", "account_bp", "/api/accounts"),
              ("routes.transaction_routes", "txn_bp", "/api/transactions"),
              ("routes.loan_routes", "loan_bp", "/api/loans"),
              ("routes.notification_routes", "notif_bp", "/api/notifications"),
              ("routes.dashboard_routes", "dash_bp", "/api/dashboard"), ("routes.system_routes", "system_bp", "/api/system"),
              ("routes.admin_routes", "admin_bp", "/api/admin")]
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def create_app():
    app = Flask(__name__, static_folder="../frontend", static_url_path="")
    app.url_map.strict_slashes = False  # /api/x and /api/x/ behave the same; no 308 redirects
    register_error_handlers(app)

    for module, var, prefix in BLUEPRINTS:
        try:
            app.register_blueprint(getattr(importlib.import_module(module), var), url_prefix=prefix)
        except ModuleNotFoundError as e:
            if e.name != module:  # a real missing dependency inside an existing module must not be hidden
                raise
            app.logger.warning("Blueprint module %s not found - skipped", module)

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.route("/api/<path:_p>", methods=METHODS)
    def api_unknown(_p):  # JSON 404 for unknown /api paths on any verb; 405 if the path exists for another verb
        adapter = app.url_map.bind_to_environ(request.environ)
        if any(adapter.match(method=m)[0] not in ("api_unknown", "static") for m in METHODS):
            raise MethodNotAllowed()
        raise NotFound()

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    create_app().run(host="127.0.0.1", port=config.FLASK_PORT, debug=False)
