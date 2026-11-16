# ABC Bank (toy banking web app)

Flask + MySQL backend, plain HTML/CSS/JS frontend. Flask serves both, so there is only one thing to run.

## Run (Linux Mint / Ubuntu / Debian, or Arch Linux)

```bash
git clone https://github.com/Abhishek-mistry/abc-bank.git && cd abc-bank
./start.sh            # if not executable:  bash start.sh
```

Then open <http://127.0.0.1:5000>. Stop with Ctrl+C.

`start.sh` detects your package manager (`apt` or `pacman`) and installs/starts MySQL (Debian family) or MariaDB (Arch) accordingly — MariaDB is a drop-in, wire-compatible replacement, so the backend needs no changes. On Arch it also runs the one-time `mariadb-install-db` step that package doesn't do automatically. The script asks for your sudo password once on first run; after that it needs no sudo.

| Command | What it does |
|---|---|
| `./start.sh` | start the app (sets everything up if needed) |
| `./start.sh --reset` | wipe the database back to the starting data, then start |
| `./start.sh --no-browser` | don't auto-open the browser |
| `FLASK_PORT=5001 ./start.sh` | use another port |

## Accounts

| Login | Password | What it is |
|---|---|---|
| `demo` | `demo123` | the single demo customer (account `100000000001`, balance 10,000.00) |
| `officer` | `officer123` | staff account: opens the **Officer Dashboard** (`admin.html`) instead of the customer pages |

Customers never see any testing tools. The Officer Dashboard has: overview and ledger check, the loan **review queue** (approve / reject / run the automatic rules), all loans, customers, recent transactions, and **Testing Tools** (failure simulation and reset-to-starting-data). To try *Send Money* you need a second account: register one on the login page.

## What is in the folder

```
start.sh              launcher
backend/              Flask API (app.py) + schema, services, selfcheck_*.py
frontend/             the pages Flask serves at /  (graphics in frontend/img)
.venv/                ready-made Python environment (Python 3.12, x86_64)
wheels/               the same dependencies as offline wheel files
requirements.lock     exact versions installed in .venv
docs/                 API-reference.md, design, validation report, amendments
```

If `.venv` does not work on your machine (a different Python version), `start.sh` rebuilds it automatically from `wheels/`, or from PyPI if the wheels do not fit.

## Debugging notes

- Database settings (defaults): DB `abc_bank`, user `abc_user`, password `abc_pass`, `127.0.0.1:3306`. Override with the `DB_*` env vars.
- MySQL/MariaDB root has a password? Run `MYSQL_ROOT_PASSWORD=yourpass ./start.sh` once.
- On Arch, the service is `mariadb.service` (the script starts whichever of `mysql`/`mariadb` exists); check it with `sudo systemctl status mariadb`. On Mint/Ubuntu it's `mysql.service`.
- `DEBUG_TOOLS=1` (default) enables the officer-only `PUT /api/admin/simulation` (fake failures) and `POST /api/admin/reset`, and honours the per-request `simulate_failure` body field. Set `DEBUG_TOOLS=0` for anything that is not a test machine.
- Health: <http://127.0.0.1:5000/api/system/health>. Ledger integrity is in the Officer Dashboard (Overview / Testing Tools).
- Backend self-tests (they seed extra fixture users alice/bob/carol; each one resets the DB; run in this order, the last two need the server running):
  ```bash
  .venv/bin/python backend/selfcheck_db.py
  .venv/bin/python backend/selfcheck_api.py
  .venv/bin/python backend/selfcheck_txn.py
  .venv/bin/python backend/selfcheck_loans.py
  ```
- Uploaded loan documents go to `backend/uploads/`.

## Known gaps

- This package was assembled but not run against a live MySQL, so expect to do the first debugging pass yourself.
