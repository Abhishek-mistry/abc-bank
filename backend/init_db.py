import argparse
import os
import re
from decimal import Decimal

from werkzeug.security import generate_password_hash

import db
from utils import new_ref

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

# Default seed: the internal bank account, ONE demo customer and ONE loan officer (no bank account).
# (user_id, username, password, full_name, phone, account_id, account_number, final balance, is_system, role)
# account_id/account_number/balance are None for users without an account.
SEED_USERS = [
    (1, "__bank__", None, "ABC Bank", "0000000000", 1, "000000000001", "-10000.00", 1, "CUSTOMER"),
    (2, "demo", "demo123", "Demo Customer", "9876500001", 2, "100000000001", "10000.00", 0, "CUSTOMER"),
    (3, "officer", "officer123", "Loan Officer", "9876500100", None, None, None, 0, "OFFICER"),
]
# (type, from_account, to_account, amount, description, initiated_by)
SEED_TXNS = [("DEPOSIT", 1, 2, "10000.00", "Opening balance", 2)]

# Fixtures used ONLY by the backend selfcheck_*.py scripts (several customers to transfer between).
TEST_USERS = [
    (1, "__bank__", None, "ABC Bank", "0000000000", 1, "000000000001", "-40000.00", 1, "CUSTOMER"),
    (2, "alice", "alice123", "Alice Sharma", "9876500001", 2, "100000000001", "10000.00", 0, "CUSTOMER"),
    (3, "bob", "bob123", "Bob Singh", "9876500002", 3, "100000000002", "5000.00", 0, "CUSTOMER"),
    (4, "carol", "carol123", "Carol Mehta", "9876500003", 4, "100000000003", "25000.00", 0, "CUSTOMER"),
    (5, "officer", "officer123", "Loan Officer", "9876500100", None, None, None, 0, "OFFICER"),
]
TEST_TXNS = [("DEPOSIT", 1, 2, "11000.00", "Opening balance", 2), ("DEPOSIT", 1, 3, "4000.00", "Opening balance", 3),
             ("DEPOSIT", 1, 4, "25000.00", "Opening balance", 4), ("TRANSFER", 2, 3, "1000.00", "Seed transfer", 2)]


def create_schema():
    sql = re.sub(r"--[^\n]*", "", open(SCHEMA, encoding="utf-8").read())
    conn = db.get_connection()  # one connection: SET FOREIGN_KEY_CHECKS is session-scoped
    try:
        cur = conn.cursor()
        for stmt in filter(None, (s.strip() for s in sql.split(";"))):
            cur.execute(stmt)
        cur.close()
    finally:
        conn.close()


def seed(test_fixtures=False):
    users, txns = (TEST_USERS, TEST_TXNS) if test_fixtures else (SEED_USERS, SEED_TXNS)
    with db.transaction() as cur:
        for uid, name, pw, full, phone, aid, num, bal, sysflag, role in users:
            cur.execute("INSERT INTO users (user_id, username, password_hash, full_name, email, phone, is_system, role) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (uid, name, generate_password_hash(pw) if pw else "!unusable", full,
                         f"{name}@abcbank.test", phone, sysflag, role))
            if aid is not None:
                cur.execute("INSERT INTO accounts (account_id, account_number, user_id, balance, is_system) "
                            "VALUES (%s,%s,%s,%s,%s)", (aid, num, uid, Decimal(bal), sysflag))
        running = {}
        for tid, (typ, frm, to, amt, desc, by) in enumerate(txns, 1):
            amt = Decimal(amt)
            cur.execute("INSERT INTO transactions (txn_id, txn_ref, txn_type, from_account_id, to_account_id, amount,"
                        " status, description, initiated_by, completed_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,'COMPLETED',%s,%s,UTC_TIMESTAMP())",
                        (tid, new_ref(), typ, frm, to, amt, desc, by))
            for acct, etype, delta in ((frm, "DEBIT", -amt), (to, "CREDIT", amt)):
                running[acct] = running.get(acct, Decimal("0")) + delta
                cur.execute("INSERT INTO ledger_entries (txn_id, account_id, entry_type, amount, balance_after) "
                            "VALUES (%s,%s,%s,%s,%s)", (tid, acct, etype, amt, running[acct]))
        assert running == {u[5]: Decimal(u[7]) for u in users if u[5] is not None}, "seed ledger does not match seed balances"
        cur.execute("INSERT INTO system_settings (setting_key, setting_value) VALUES ('sim_mode','NONE'),"
                    "('sim_probability','0.30')")


def reset_database(test_fixtures=False):
    create_schema()
    seed(test_fixtures)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Create the ABC Bank schema and seed data")
    ap.add_argument("--no-seed", action="store_true", help="create empty tables only")
    ap.add_argument("--test-fixtures", action="store_true", help="seed alice/bob/carol for the selfcheck scripts")
    args = ap.parse_args()
    create_schema()
    if not args.no_seed:
        seed(args.test_fixtures)
    print("Database ready.")
