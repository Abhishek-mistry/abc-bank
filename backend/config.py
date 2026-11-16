import os

_e = os.environ.get
DB = dict(host=_e("DB_HOST", "127.0.0.1"), port=int(_e("DB_PORT", "3306")), user=_e("DB_USER", "abc_user"),
          password=_e("DB_PASSWORD", "abc_pass"), database=_e("DB_NAME", "abc_bank"))
FLASK_PORT = int(_e("FLASK_PORT", "5000"))
DEBUG_TOOLS = _e("DEBUG_TOOLS", "1") == "1"
UPLOAD_DIR = _e("UPLOAD_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads"))
