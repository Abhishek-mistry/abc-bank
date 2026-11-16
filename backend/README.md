# ABC Bank backend — foundation (01llm) · built against structural_design.md v1.0

## Bootstrap (once, by a human)
```sql
CREATE DATABASE abc_bank CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'abc_user'@'localhost' IDENTIFIED BY 'abc_pass';
GRANT ALL PRIVILEGES ON abc_bank.* TO 'abc_user'@'localhost';
```
MySQL >= 8.0.16 required (CHECK constraints must be enforced). If `localhost` resolves to a socket on your machine,
also create/grant `'abc_user'@'127.0.0.1'`.

## Run
```
pip install -r backend/requirements.txt
python backend/init_db.py        # schema + seed   (--no-seed = empty tables)
python backend/app.py            # http://127.0.0.1:5000  (API /api, frontend /)
python backend/selfcheck_db.py   # foundation self-test, PASS/FAIL per check (resets DB to seed)
```

## Selfchecks (one at a time, in this order; each resets the DB; the last three need the server on :5000)
```
python backend/selfcheck_db.py && python backend/selfcheck_txn.py && python backend/selfcheck_loans.py && python backend/selfcheck_api.py
```
Then `GET /api/system/integrity` must return `"ok": true`. Integrity SQL lives only in `services/health_service.py`.

## Reset the database
`python backend/init_db.py` (drop + create + seed, safe to repeat) or `init_db.reset_database()` in code
(`POST /api/system/reset` uses it when `DEBUG_TOOLS=1`).

## Env vars (defaults)
`DB_HOST=127.0.0.1` `DB_PORT=3306` `DB_USER=abc_user` `DB_PASSWORD=abc_pass` `DB_NAME=abc_bank`
`FLASK_PORT=5000` `DEBUG_TOOLS=1` `UPLOAD_DIR=backend/uploads`

## Notes for other agents
- `db.run_transaction(fn, retries=3)`: `retries` = total attempts; sleeps 0.05 s, 0.10 s between them; then `ApiError("TXN_RETRY_EXHAUSTED")`.
- `utils.validate_fields(data, rules)`: `rules = {field: {"required": True, "min_len", "max_len", "regex", "choices", "msg"}}`; returns `{field: stripped str}` for supplied fields.
- `middleware.get_page_args()`: `page_size` > 50 is clamped to 50; non-numeric or < 1 -> `VALIDATION_ERROR`.
- `parse_money` accepts JSON floats (`10.5`) via `str()`; anything with > 2 decimals, sign or exponent is rejected.
- Unknown `/api/*` paths return JSON 404 for every verb; a known path with the wrong verb returns 405.
- `app.url_map.strict_slashes = False`: `/api/x` and `/api/x/` both work (no 308 redirects).

## Interpretations in force (design v1.0; proposed v1.1 wording in AMENDMENTS.md)
- Loan totals follow §9.4 (`total_payable = sum of emi_k`), so the §7.4 example becomes `total_interest 2470.90`, `total_payable 52470.90`.
- `AMOUNT_EXCEEDS_LIMIT` never fires alone; it always co-occurs with `EMI_TOO_HIGH`.
- `current_step` is 4 once details, income details and all 3 documents are saved (the guarantor is entered in step 4).
- Loan `accept` honours only the global simulation mode; `repay` also honours body `simulate_failure` (only while `DEBUG_TOOLS=1`).
- Staff: users have a `role` (`CUSTOMER` / `OFFICER`). `/api/admin/*` needs an OFFICER (`403 FORBIDDEN` for customers); officers get `403` on customer APIs. Loan review is `POST /api/admin/loans/{id}/review` (customers can no longer review their own loans).
- 02 never emits `LIMIT_EXCEEDED` (money limits -> `VALIDATION_ERROR`); 04 uses it for the 5-open-accounts limit.
- The same `idempotency_key` with a different body by the same user replays the original transaction (§8.8 read literally).
- `db.run_transaction(fn, retries=3)`: 3 total attempts. `db.get_connection()` waits (up to 30 s) when all 32 pooled connections are busy.
- A FAILED history row is written for unexpected exceptions too (`failure_code = INTERNAL_ERROR`), for transfers and loan accept/repay alike.
