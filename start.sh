#!/usr/bin/env bash
# ABC Bank - one-command launcher for Linux Mint / Ubuntu / Debian (apt) and Arch Linux (pacman).
#
#   ./start.sh              start the app  (sets up MySQL/MariaDB + database on first run)
#   ./start.sh --reset      wipe the database back to the starting data, then start
#   ./start.sh --no-browser don't open the browser automatically
#   ./start.sh --help
#
# Open http://127.0.0.1:5000   (customer: demo/demo123 - staff: officer/officer123)
# Stop with Ctrl+C.

set -uo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" || exit 1
ROOT="$PWD"

RESET=0
OPEN_BROWSER=1
for arg in "$@"; do
  case "$arg" in
    --reset) RESET=1 ;;
    --no-browser) OPEN_BROWSER=0 ;;
    -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
  esac
done

# Same defaults as backend/config.py. Override by exporting them before running.
export DB_HOST="${DB_HOST:-127.0.0.1}"
export DB_PORT="${DB_PORT:-3306}"
export DB_USER="${DB_USER:-abc_user}"
export DB_PASSWORD="${DB_PASSWORD:-abc_pass}"
export DB_NAME="${DB_NAME:-abc_bank}"
export FLASK_PORT="${FLASK_PORT:-5000}"
export DEBUG_TOOLS="${DEBUG_TOOLS:-1}"

PY="$ROOT/.venv/bin/python"

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Which package manager this machine uses. Everything OS-specific branches on this.
if command -v pacman >/dev/null 2>&1; then PKG=pacman
elif command -v apt-get >/dev/null 2>&1; then PKG=apt
else PKG=unknown
fi

# ---------------------------------------------------------------- 1. Python venv
fix_venv_paths() {
  # The .venv was built in another folder. Its bin/ scripts (pip, activate) still
  # point there; rewrite them if this folder moved. bin/python itself needs no fix.
  local old new="$ROOT/.venv"
  [ -f "$ROOT/.venv/.built_at" ] || return 0
  old="$(cat "$ROOT/.venv/.built_at")"
  if [ -n "$old" ] && [ "$old" != "$new" ]; then
    grep -rIlF -- "$old" "$ROOT/.venv/bin" 2>/dev/null | while IFS= read -r f; do
      sed -i "s#$old#$new#g" "$f"
    done
    echo "$new" > "$ROOT/.venv/.built_at"
  fi
}

venv_ok() { [ -x "$PY" ] && "$PY" -c "import flask, mysql.connector, requests" >/dev/null 2>&1; }

rebuild_venv() {
  warn "Bundled .venv doesn't work on this machine (different Python?). Rebuilding it..."
  command -v python3 >/dev/null || die "python3 not found. Install it: $([ "$PKG" = pacman ] && echo 'sudo pacman -S python' || echo 'sudo apt install python3')"
  rm -rf "$ROOT/.venv"
  if ! python3 -m venv "$ROOT/.venv" 2>/dev/null; then
    if [ "$PKG" = apt ]; then
      warn "python3-venv is missing; installing it (sudo password may be asked)"
      sudo apt-get install -y python3-venv || die "could not install python3-venv"
      rm -rf "$ROOT/.venv"
      python3 -m venv "$ROOT/.venv" || die "could not create .venv"
    else
      die "python3 -m venv failed. On Arch this ships with the 'python' package - try: sudo pacman -S --needed python"
    fi
  fi
  if ! "$PY" -m pip install -q --no-index --find-links "$ROOT/wheels" -r "$ROOT/requirements.lock" 2>/dev/null; then
    warn "Bundled wheels don't fit this Python; downloading from PyPI instead"
    "$PY" -m pip install -q -r "$ROOT/backend/requirements.txt" || die "pip install failed"
  fi
  echo "$ROOT/.venv" > "$ROOT/.venv/.built_at"
}

say "Checking Python environment"
fix_venv_paths
venv_ok || rebuild_venv
venv_ok || die "Python dependencies still not importable. See README.md (Troubleshooting)."
echo "Python: $("$PY" --version)  |  Flask + mysql-connector OK"

# ---------------------------------------------------------------- 2. MySQL + database
db_connect_ok() {
  "$PY" - <<'PY' >/dev/null 2>&1
import os, mysql.connector
mysql.connector.connect(host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
    user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
    database=os.environ["DB_NAME"], connection_timeout=3).close()
PY
}

mysql_admin() {  # run SQL from stdin as MySQL root (auth_socket via sudo, or MYSQL_ROOT_PASSWORD)
  if [ -n "${MYSQL_ROOT_PASSWORD:-}" ]; then
    mysql -h "$DB_HOST" -P "$DB_PORT" -uroot --password="$MYSQL_ROOT_PASSWORD"
  else
    sudo mysql
  fi
}

install_db_pkg() {
  case "$PKG" in
    apt)
      sudo apt-get update || warn "apt-get update reported errors (a third-party repo?); trying to install anyway"
      sudo apt-get install -y mysql-server || die "mysql-server install failed. Install it manually, then run ./start.sh again."
      ;;
    pacman)
      sudo pacman -Sy --noconfirm || warn "pacman -Sy reported errors; trying to install anyway"
      sudo pacman -S --needed --noconfirm mariadb mariadb-clients || die "mariadb install failed. Install it manually (sudo pacman -S mariadb mariadb-clients), then run ./start.sh again."
      ;;
    *) die "No supported package manager found (need apt or pacman). Install MySQL/MariaDB yourself, then run ./start.sh again." ;;
  esac
}

# Arch's mariadb package, unlike Debian/Ubuntu's, does not auto-initialize the data directory on install.
init_datadir_if_needed() {
  [ "$PKG" = pacman ] || return 0
  [ -d /var/lib/mysql/mysql ] && return 0
  say "Initializing MariaDB data directory (first run on this machine)"
  sudo mkdir -p /var/lib/mysql
  sudo chown mysql:mysql /var/lib/mysql
  local tool
  tool=$(command -v mariadb-install-db || command -v mysql_install_db) || die "mariadb-install-db not found"
  sudo "$tool" --datadir=/var/lib/mysql --user=mysql || die "mariadb-install-db failed"
}

SQL_SERVICE=""
start_db_service() {
  local unit
  for unit in mysql mariadb; do
    if sudo systemctl enable --now "$unit" >/dev/null 2>&1; then SQL_SERVICE="$unit"; return 0; fi
  done
  for unit in mysql mariadb; do
    if sudo service "$unit" start >/dev/null 2>&1; then SQL_SERVICE="$unit"; return 0; fi
  done
  return 1
}

ensure_mysql() {
  if ! command -v mysqld >/dev/null 2>&1 && ! command -v mariadbd >/dev/null 2>&1 \
     && ! [ -x /usr/sbin/mysqld ] && ! [ -x /usr/bin/mariadbd ]; then
    say "MySQL/MariaDB server not installed - installing it (sudo password may be asked)"
    install_db_pkg
  fi
  command -v mysqladmin >/dev/null 2>&1 || [ "$PKG" != pacman ] || sudo pacman -S --needed --noconfirm mariadb-clients
  init_datadir_if_needed
  say "Starting the database service"
  start_db_service || die "could not start the mysql/mariadb service"
  local i
  for i in $(seq 1 30); do
    if sudo mysqladmin ping --silent >/dev/null 2>&1 || mysqladmin -h "$DB_HOST" -P "$DB_PORT" ping --silent >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  die "MySQL/MariaDB did not come up within 30 s. Check: sudo systemctl status ${SQL_SERVICE:-mysql}"
}

provision_db() {
  say "Creating database '$DB_NAME' and user '$DB_USER'"
  mysql_admin <<SQL || die "Could not run admin SQL. If MySQL root has a password: MYSQL_ROOT_PASSWORD=yourpass ./start.sh"
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
CREATE USER IF NOT EXISTS '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
}

say "Checking database connection"
if db_connect_ok; then
  echo "Connected to MySQL as $DB_USER (database $DB_NAME)"
else
  ensure_mysql
  provision_db
  db_connect_ok || die "Still cannot connect as $DB_USER to $DB_NAME on $DB_HOST:$DB_PORT."
  echo "Connected to MySQL as $DB_USER (database $DB_NAME)"
fi

tables_present() {
  "$PY" - <<'PY' >/dev/null 2>&1
import os, sys, mysql.connector
c = mysql.connector.connect(host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"]),
    user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"], database=os.environ["DB_NAME"])
cur = c.cursor(); cur.execute("SHOW COLUMNS FROM users LIKE 'role'")  # 'role' = current schema; an older DB is rebuilt
sys.exit(0 if cur.fetchone() else 1)
PY
}

if [ "$RESET" = 1 ] || ! tables_present; then
  say "Creating schema and starting data"
  "$PY" "$ROOT/backend/init_db.py" || die "init_db.py failed (see output above)"
else
  echo "Schema already present (use ./start.sh --reset to wipe back to the starting data)"
fi

# ---------------------------------------------------------------- 3. Run the backend
mkdir -p "$ROOT/backend/uploads"

if ss -ltn 2>/dev/null | grep -q ":$FLASK_PORT "; then
  die "Port $FLASK_PORT is already in use. Stop the other process, or run: FLASK_PORT=5001 ./start.sh"
fi

URL="http://127.0.0.1:$FLASK_PORT"
if [ "$OPEN_BROWSER" = 1 ] && command -v xdg-open >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  (
    for _ in $(seq 1 30); do
      if "$PY" -c "import urllib.request as u; u.urlopen('$URL/api/system/health', timeout=1)" >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1
        exit 0
      fi
      sleep 1
    done
  ) &
fi

say "ABC Bank is starting at $URL   (Ctrl+C to stop)"
echo "Customer login: demo/demo123     Officer/testing dashboard login: officer/officer123"
echo "Health: $URL/api/system/health"
echo
cd "$ROOT/backend" && exec "$PY" app.py
