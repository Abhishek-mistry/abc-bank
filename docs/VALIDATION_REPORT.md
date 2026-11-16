# VALIDATION_REPORT — ABC Bank backend (VAL, 2026-09-28)

Design: `structural_design.md` v1.0. Inputs received: design, `memotoall.md`, `01toall-3.md` (holds the 01/02/03/04 notices), `backend.zip` (02/03/04 files + selfchecks), `01_foundation.zip` (01 files). `00do01..04.md` were not supplied; not needed, the notices covered the interpretations.

**Environment (real, not stand-ins):** MySQL 8.0.46 (Ubuntu 24.04), Python 3.12.3, Flask 3.1.3, mysql-connector-python (`mysql.connector.__version__` = 26.7.0), Flask dev server (threaded) on :5000.

## Status

| Agent | Status | Why |
|---|---|---|
| 01 | **FIXED** | `db.get_connection()` surfaced pool exhaustion as HTTP 500 under >32 concurrent requests; `requirements.txt` lacked `Werkzeug`; README lacked interpretations |
| 02 | **FIXED** | `selfcheck_txn` B1 grep gate failed on 04's deliberate corruption `UPDATE`s; duplicated integrity SQL |
| 03 | **FIXED** | unexpected exception in `accept`/`repay` left no FAILED history row (§8.6); unused imports; duplicated integrity SQL |
| 04 | **PASS** | no change needed |

## Findings

| # | agent / file | symptom | design § | fix | lines |
|---|---|---|---|---|---|
| 1 | 01 `db.py` | `selfcheck_txn` B7b failed (74/75): 40 parallel opposing transfers, pool size 32, connector pool is non-blocking, so `PoolError` became 500 `INTERNAL_ERROR` | §8.11, §10 (pool 32) | `get_connection` retries `_pool.get_connection()` for up to 30 s on `PoolError`. Safe: I checked that no 02/03/04 code acquires a second connection while holding a transaction | +10 −1 |
| 2 | 02 `selfcheck_txn.py` | B1 grep gate FAIL: it scanned `selfcheck_api.py`, which deliberately runs `UPDATE accounts SET balance` to corrupt I2/I5 | §8.1 | gate now `--exclude=selfcheck_*.py` (app code only) | +1 −1 |
| 3 | 03 `services/loan_service.py` | `_money_op` caught only `ApiError`/`SimulatedNetworkError`; an unexpected exception rolled back correctly but wrote **no** FAILED row, unlike 02's `_run` (reproduced in-process before the fix, passes after) | §8.6, §9.7 | `except Exception`; code `INTERNAL_ERROR` for unknown exceptions (still gated by "money attempt was made" and `!= VALIDATION_ERROR`) | +3 −2 |
| 4 | 02 `selfcheck_txn.py`, 03 `selfcheck_loans.py` | integrity SQL copied into two selfchecks (I1–I5 / I1–I6) | §4.1, rule 1 | both call `health_service.integrity_report()`. `selfcheck_api` mutation-tests I1–I6 against it, so the oracle is still independently validated. Label now says I1–I6 | txn +3 −13, loans +2 −14 |
| 5 | 03 `selfcheck_loans.py` | unused imports `io`, `threading` | rule 6 | removed | +1 −1 |
| 6 | 01 `requirements.txt` | `werkzeug` imported directly (4 files) but not listed | Phase 6 | added `Werkzeug>=3.0` | +1 |
| 7 | 01 `README.md` | interpretations and selfcheck order undocumented | Phase 6 | added two short sections | +14 |

Totals vs delivered files: 6 files, +35/−32 lines (`val_patch/val.patch`). Frontend, pytest, tools, docs untouched.

## Static audit (Phase 0–1)

- Phase 0: all 01–04 files from §3.2/§3.3 present after `01_foundation.zip` arrived. Missing by design: `tests/`, `frontend/`, `tools/`, `docs/`.
- 38/38 Appendix A endpoints registered with correct method/path; auth checked on each (401 `AUTH_REQUIRED` without `X-User-Id` for every `yes` row; `no` rows open). Only extra route: `GET /` (frontend index, §2). `POST /auth/login` with an empty body returns 401 `INVALID_CREDENTIALS` (04 interpretation 2), not `AUTH_REQUIRED`.
- 8 blueprint variables and prefixes match §3.4.
- All §10 signatures match exactly. Additive only: `health_summary(check_integrity=True)`, `failure_sim.resolve_mode`, `failure_sim.MODES`, `transfer_service._run` (→ AMENDMENTS).
- `ERROR_STATUS` equals Appendix B (21 codes, all statuses). Every error code used in source is in Appendix B. Notification types = the 11 in §6.
- `float(`: only `failure_sim` probability, never money. `UPDATE accounts SET balance`: only `ledger.py:37` (plus deliberate corruption in `selfcheck_api`). No `commit(`/`rollback(` in `ledger.py`. Two f-string SQLs (`notification_routes`, `ledger._post`) interpolate constants only. `pyflakes` clean after fix 5. No debug prints.
- **Limit of this audit:** table names, error codes, notification types, endpoints and function signatures were checked mechanically. Column names and JSON keys were not exhaustively grepped; they are covered at runtime by the ~275 selfcheck assertions, which query every table and shape-check every response type.

## Cross-agent interface matrix (Phase 2, verified on MySQL 8)

| Caller → callee | Result |
|---|---|
| 02/03/04 → `ApiError.code/.message/.details` | OK (`details` always a dict) |
| 03 → `failure_sim.resolve_mode` (once before txn, concrete mode to `move_money` and `maybe_drop_response`) | OK; fixed modes never touch DB, `RANDOM` resolved once |
| 03 → `ledger.find_by_idempotency_key(cur, key, uid)`, `get_transaction_dict(ref, uid[, cur])`, `record_failed_txn(**ctx)` | OK |
| 04 → `transfer_service.list_transactions(uid, {}, 1, 5)["items"]` | OK |
| 04 → `failure_sim.get_global/set_global/MODES` (6 modes) | OK |
| 04 → `db.transaction()` cursor `.rowcount` (`read-all`) | OK (matched rows) |
| 02/03/04 → `db.run_transaction` | nobody passes `retries`; 3 = total attempts; `TXN_RETRY_EXHAUSTED` is an `ApiError`, so both 02 and 03 record it |
| 02/03 → nested connections inside a transaction | none |

Decided interpretations kept (no check proved them harmful): §9.4 totals win (`total_interest 2470.90`); `AMOUNT_EXCEEDS_LIMIT` co-occurs with `EMI_TOO_HIGH`; `current_step`=4; `accept` honours global sim only; 02 never emits `LIMIT_EXCEEDED` (04 uses it for the 5-open-accounts limit); same key + different body replays the original. The last one is **not** fixed: §8.8 says to replay on key match, so it is design-conformant, and a mismatch check needs a new error code (→ AMENDMENTS).

## Evidence

Fresh DB (`DROP/CREATE DATABASE`) → `init_db.py` → server → selfchecks one at a time (Phase 5):

```
selfcheck_db     RESULT: ALL PASS            (15 PASS lines)
selfcheck_txn    75/75 checks passed         (first run: 2/12 with no server, then 74/75 on B7b)
selfcheck_loans  ALL PASS                    (102 PASS lines)
selfcheck_api    ALL PASS                    (83 PASS lines)
GET /api/system/integrity -> ok: true        I1..I6 all true
information_schema: 10 tables, 5 CHECK constraints all ENFORCED, no stray _bak table
server log: 0 tracebacks / PoolError during the regression run
```

Phase 4, `/tmp/phase4.py`, 23/23 (re-run after the patches):

```
A  20 parallel opposing transfers, random amounts: all 201, balances == serial result, integrity ok
B  BEFORE_DEBIT / AFTER_DEBIT / BEFORE_COMMIT on transfer and deposit: 503, balances unchanged, integrity ok
B  DROP_RESPONSE: 504, no txn_ref in body, money moved once; retry same key: 200 idempotent_replay:true, no 2nd debit
B  RANDOM p=0.6, 30 logical transfers with same-key retries: each applied exactly once, integrity ok
C  accept under global BEFORE_COMMIT: 503, loan stays APPROVED, no schedule, FAILED row has loan_id
C  accept under global DROP_RESPONSE: 504, loan ACTIVE, disbursed once; retry same key: 200, no 2nd disbursement
C  6 parallel accept: one 200, five 409 INVALID_STATE, one disbursement
C  10 parallel repay: all 201, installments 1..10 exactly once, debit = 10 x EMI, integrity ok
```

In-process regression for finding 3: patched `ledger.move_money` to raise → one FAILED row (`INTERNAL_ERROR`, `LOAN_DISBURSEMENT`, `loan_id`), loan still APPROVED, balance unchanged.

## Remaining risks

1. **MySQL version:** run on 8.0.46 only. The 8.0.16 floor (CHECK enforcement) was not exercised.
2. **Not validated:** frontend and `backend/tests/` (not provided, out of scope). Their first run may still expose contract drift.
3. **Pool wait:** if the pool stays exhausted for 30 s, `PoolError` still surfaces as 500. Not reachable in my runs (max 40 concurrent).
4. **Repay lock order:** 03 locks loan → next `repayment_schedule` row → accounts (via `move_money`). §8.3 lists only loan → txn → accounts. Safe because the loan lock serialises repays; the 10-way parallel test showed no deadlock. Documented as an amendment.
5. **`INTERNAL_ERROR` FAILED rows** store `str(e)` as `failure_reason` (02's existing behaviour, now also 03). A raw DB error message could be visible in history. Proposed: fixed generic text.
6. **Duplication kept:** `loan_service._money_op` ≈ `transfer_service._run` (different FAILED-row gating). Merging means rewriting verified code, so I left it.
7. **Same key, different body** replays the original (known issue, design-conformant).
8. `selfcheck_*` files reset the DB: never run them concurrently or alongside pytest.
