"""04llm - ledger integrity (I1-I6, §4.1) and health summary."""
from decimal import Decimal

from db import fetch_all, fetch_one
from money import money_str
from services import failure_sim

_D = "SUM(CASE e.entry_type WHEN 'DEBIT' THEN e.amount END)"
_C = "SUM(CASE e.entry_type WHEN 'CREDIT' THEN e.amount END)"
CHECKS = {
    "I1": f"SELECT t.txn_id, t.status, COALESCE({_D},0) AS debit, COALESCE({_C},0) AS credit FROM transactions t "
          "LEFT JOIN ledger_entries e ON e.txn_id=t.txn_id WHERE t.status IN ('COMPLETED','REVERSED') "
          "GROUP BY t.txn_id, t.status HAVING debit<>credit OR debit=0 LIMIT 50",
    "I2": "SELECT a.account_id, a.balance AS actual, COALESCE(SUM(CASE e.entry_type WHEN 'CREDIT' THEN e.amount ELSE -e.amount END),0) AS expected "
          "FROM accounts a LEFT JOIN ledger_entries e ON e.account_id=a.account_id GROUP BY a.account_id, a.balance HAVING actual<>expected LIMIT 50",
    "I3": "SELECT t.txn_id, t.status, COUNT(e.entry_id) AS entries FROM transactions t LEFT JOIN ledger_entries e ON e.txn_id=t.txn_id "
          "WHERE t.status IN ('FAILED','PENDING') GROUP BY t.txn_id, t.status HAVING t.status='PENDING' OR entries>0 LIMIT 50",
    "I4": "SELECT SUM(balance) AS total FROM accounts HAVING total<>0",
    "I5": "SELECT account_id, balance FROM accounts WHERE is_system=0 AND balance<0 LIMIT 50",
    "I6": "SELECT l.loan_id, l.status, l.tenure_months AS expected_rows, COUNT(s.installment_id) AS rows_found, "
          "COALESCE(SUM(s.principal_component),0) AS principal_sum, l.approved_amount, COALESCE(SUM(s.status<>'PAID'),0) AS unpaid "
          "FROM loans l LEFT JOIN repayment_schedule s ON s.loan_id=l.loan_id WHERE l.status IN ('ACTIVE','CLOSED') "
          "GROUP BY l.loan_id, l.status, l.tenure_months, l.approved_amount "
          "HAVING rows_found<>expected_rows OR principal_sum<>l.approved_amount OR (l.status='CLOSED' AND unpaid>0) LIMIT 50",
}


def _plain(row):
    return {k: money_str(v) if isinstance(v, Decimal) else v for k, v in row.items()}


def integrity_report():
    checks = {}
    for name, sql in CHECKS.items():
        rows = fetch_all(sql)
        checks[name] = {"ok": not rows, "violations": [_plain(r) for r in rows[:50]]}
    return {"ok": all(c["ok"] for c in checks.values()), "checks": checks}


def health_summary(check_integrity=True):
    try:
        fetch_one("SELECT 1 AS x")
        db_up = True
    except Exception:
        db_up = False
    failed, mode = 0, "NONE"
    if db_up:
        failed = fetch_one("SELECT COUNT(*) AS n FROM transactions WHERE status='FAILED' "
                           "AND created_at >= UTC_TIMESTAMP() - INTERVAL 24 HOUR")["n"]
        mode = failure_sim.get_global()["mode"]
    if not db_up or (check_integrity and not integrity_report()["ok"]):
        status = "DEGRADED"
    else:
        status = "SIMULATION_ACTIVE" if mode != "NONE" else "ALL_GOOD"
    return {"status": status, "db": "UP" if db_up else "DOWN", "simulation_mode": mode, "failed_txns_24h": failed}
