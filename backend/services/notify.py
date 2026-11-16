TYPES = {"TRANSFER_SENT", "TRANSFER_RECEIVED", "TRANSFER_FAILED", "TRANSFER_REVERSED", "DEPOSIT",
         "LOAN_SUBMITTED", "LOAN_APPROVED", "LOAN_REJECTED", "LOAN_DISBURSED", "REPAYMENT_PAID", "LOAN_CLOSED"}


def create_notification(cur, user_id, ntype, title, message, related_ref=None):
    if ntype not in TYPES:
        raise ValueError(f"unknown notification type {ntype!r}")
    cur.execute("INSERT INTO notifications (user_id, type, title, message, related_ref) VALUES (%s,%s,%s,%s,%s)",
                (user_id, ntype, title[:100], message[:255], None if related_ref is None else str(related_ref)[:40]))
    return cur.lastrowid
