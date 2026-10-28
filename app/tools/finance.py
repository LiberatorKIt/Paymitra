"""Deterministic money maths. No LLM ever computes a number in PayMitra.

Every function here is unit-tested in tests/test_tools.py.
"""
from datetime import date

from app import config


def days_between(start: date, end: date) -> int:
    return (end - start).days


def invoice_age(invoice_date: date, today: date) -> int:
    return max(0, (today - invoice_date).days)


def ageing_bucket(age_days: int) -> str:
    if age_days <= 30:
        return "0-30"
    if age_days <= 45:
        return "31-45"
    if age_days <= 60:
        return "46-60"
    return "60+"


def sec16_interest(amount: float, days_late: int, bank_rate_pct: float | None = None) -> float:
    """MSMED Act Sec 16: compound interest with monthly rests at 3x the RBI bank rate.

    Months are taken as 30 days; a part month accrues simple interest.
    Illustrative: have a CA confirm the method before using it in a notice.
    """
    if days_late <= 0 or amount <= 0:
        return 0.0
    rate = config.BANK_RATE_PCT if bank_rate_pct is None else bank_rate_pct
    monthly = 3 * rate / 100 / 12
    full_months, extra_days = divmod(days_late, 30)
    value = amount * (1 + monthly) ** full_months
    value *= 1 + monthly * extra_days / 30
    return round(value - amount, 2)


def od_cost(amount: float, days: int, od_rate_pct: float | None = None) -> float:
    rate = config.OD_RATE_PCT if od_rate_pct is None else od_rate_pct
    return round(amount * rate / 100 * max(days, 0) / 365, 2)


def treds_cost(amount: float, days: int, treds_rate_pct: float | None = None,
               fee_pct: float | None = None) -> float:
    rate = config.TREDS_RATE_PCT if treds_rate_pct is None else treds_rate_pct
    fee = config.TREDS_FEE_PCT if fee_pct is None else fee_pct
    return round(amount * rate / 100 * max(days, 0) / 365 + amount * fee / 100, 2)


def cheapest_option(gap_amount: float, days_needed: int, buyer_on_treds: bool,
                    cost_of_missing: float | None = None) -> tuple[str, dict]:
    """Wait vs overdraft vs TReDS for one cash gap. Returns (best, costs)."""
    costs = {
        "WAIT": round(config.MISSED_PAYROLL_COST if cost_of_missing is None else cost_of_missing, 2),
        "OD": od_cost(gap_amount, days_needed),
    }
    if buyer_on_treds:
        costs["TREDS"] = treds_cost(gap_amount, days_needed)
    best = min(costs, key=costs.get)
    return best, costs


def inr(value: float) -> str:
    """Indian-style rupee formatting: 680000 -> '₹6.80 L', 21000000 -> '₹2.10 Cr'."""
    v = float(value)
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e7:
        return f"{sign}₹{v / 1e7:.2f} Cr"
    if v >= 1e5:
        return f"{sign}₹{v / 1e5:.2f} L"
    return f"{sign}₹{v:,.0f}"
