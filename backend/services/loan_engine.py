"""Pure loan maths (design §9.2-§9.4). No DB, no Flask. Decimal only."""
from datetime import date
from decimal import Decimal as D, ROUND_HALF_UP, getcontext

from utils import add_months

getcontext().prec = 28
BASE, FLOOR, REF_RATE = D("9.00"), D("5.00"), D("9.00")
_GUARANTOR = {"SPOUSE": "1.00", "PARENT": "1.00", "SIBLING": "1.00", "CHILD": "1.00",
              "OTHER_RELATIVE": "0.50", "FRIEND": "0.00", "COLLEAGUE": "0.00"}


def _r2(x):
    return D(x).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def calc_emi(principal, annual_rate, n):
    P, rate = D(principal), D(annual_rate)
    if rate == 0:
        return _r2(P / n)
    r = rate / 12 / 100
    f = (1 + r) ** n
    return _r2(P * r * f / (f - 1))


def build_schedule(principal, annual_rate, n, first_due_date: date):
    P, r, emi = D(principal), D(annual_rate) / 12 / 100, calc_emi(principal, annual_rate, n)
    bal, rows = P, []
    for k in range(1, n + 1):
        interest = _r2(bal * r)
        principal_c = emi - interest if k < n else bal
        bal -= principal_c
        rows.append(dict(installment_no=k, due_date=add_months(first_due_date, k - 1),
                         emi_amount=emi if k < n else principal_c + interest,
                         principal_component=_r2(principal_c), interest_component=interest,
                         balance_after=_r2(bal)))
    return rows


def _ratio(monthly_income, principal, n):
    return calc_emi(principal, REF_RATE, n) / D(monthly_income)


def compute_rate(monthly_income, principal, n, relationship, has_closed_loan):
    ratio = _ratio(monthly_income, principal, n)
    d = {"income_discount": D("2.00") if ratio <= D("0.20") else D("1.00") if ratio <= D("0.35") else D("0"),
         "guarantor_discount": D(_GUARANTOR[relationship]),
         "tenure_discount": D("1.00") if n <= 12 else D("0.50") if n <= 24 else D("0"),
         "loyalty_discount": D("1.00") if has_closed_loan else D("0")}
    final = max(FLOOR, BASE - sum(d.values()))
    return {"base": str(BASE), **{k: str(_r2(v)) for k, v in d.items()}, "final_rate": str(_r2(final))}


def evaluate_application(loan, guarantor, active_loans, has_closed_loan):
    """loan needs monthly_income, requested_amount, tenure_months, aadhar_number."""
    inc, amt, n = D(loan["monthly_income"]), D(loan["requested_amount"]), int(loan["tenure_months"])
    codes = [c for c, bad in (
        ("LOW_INCOME", inc < 10000),
        ("EMI_TOO_HIGH", _ratio(inc, amt, n) > D("0.50")),
        ("AMOUNT_EXCEEDS_LIMIT", amt > 20 * inc),
        ("TOO_MANY_ACTIVE_LOANS", active_loans >= 2),
        ("GUARANTOR_SAME_AS_APPLICANT", guarantor["guarantor_aadhar"] == loan["aadhar_number"])) if bad]
    rb = compute_rate(inc, amt, n, guarantor["relationship"], has_closed_loan)
    return {"decision": "REJECT" if codes else "APPROVE", "interest_rate": D(rb["final_rate"]),
            "rejection_codes": codes, "rate_breakdown": rb}
