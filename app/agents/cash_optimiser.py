"""Agent 5 - Cash & Finance Optimiser: meet payroll at the lowest cost.

13-week forecast from expected receipts; for the first cash gap it compares
wait vs overdraft vs TReDS on the invoice that would close it. All arithmetic
is code (app/tools); the LLM only words the one-line explanation.
"""
from datetime import date

from sqlmodel import select

from app import config
from app import llm, mocks
from app.agents import buyer_intel
from app.db import Buyer, Invoice, Supplier
from app.state_machine import CLOSED_STATES
from app.tools.finance import cheapest_option, inr
from app.tools.forecast import build_forecast

AGENT = "Cash & Finance Optimiser"


def expected_inflows(session, today: date) -> list[dict]:
    out = []
    buyers = {b.id: b for b in session.exec(select(Buyer)).all()}
    for inv in session.exec(select(Invoice).where(Invoice.state.not_in(list(CLOSED_STATES)))).all():
        for p in buyer_intel.predict(session, inv, buyers[inv.buyer_id], today):
            out.append({**p, "invoice_id": inv.id, "buyer": buyers[inv.buyer_id].name})
    return out


def forecast(session, today: date | None = None) -> dict:
    today = today or config.today()
    sup = session.get(Supplier, 1)
    inflows = expected_inflows(session, today)
    fc = build_forecast(today, sup.opening_cash + _cash_movements(session), inflows, sup.payroll_amount,
                        sup.payroll_next_date, sup.monthly_bills, sup.monthly_sales)
    fc["inflows"] = sorted(inflows, key=lambda f: f["date"])
    return fc


def _cash_movements(session) -> float:
    """Credits received after the opening balance was set (TReDS money, buyer payments)."""
    from app.db import BankTxn
    return sum(t.amount for t in session.exec(select(BankTxn).where(BankTxn.live == True)).all())  # noqa: E712


def financing_proposal(session, today: date | None = None) -> dict | None:
    """Find the first cash gap and the cheapest way to close it with one invoice."""
    today = today or config.today()
    fc = forecast(session, today)
    gap = fc["first_gap"]
    if not gap:
        return None
    best = None
    for inv in session.exec(select(Invoice).where(Invoice.state.in_(
            ["SENT", "ACKNOWLEDGED", "DUE", "PROMISED", "SILENT"]))).all():
        buyer = session.get(Buyer, inv.buyer_id)
        if inv.blocker or not buyer.on_treds:
            continue
        expected = buyer_intel.predict(session, inv, buyer, today)
        if not expected or min(e["date"] for e in expected) <= gap["date"]:
            continue
        if best is None or inv.outstanding > best[0].outstanding:
            best = (inv, buyer, max(e["date"] for e in expected))
    if best is None:
        return {"gap": gap, "invoice": None}
    inv, buyer, pay_date = best
    days_needed = max(1, (pay_date - gap["date"]).days)
    choice, costs = cheapest_option(inv.outstanding, days_needed, buyer.on_treds)
    quote = mocks.treds_quote(buyer, inv.outstanding, days_needed)
    line = (f"Payroll leaves a {inr(gap['shortfall'])} gap on {gap['date']:%d %b}; {buyer.name} is expected to "
            f"pay #{inv.id} ({inr(inv.outstanding)}) around {pay_date:%d %b}, {days_needed} days later. "
            + ", ".join(f"{k} {inr(v)}" for k, v in costs.items()) + f". Cheapest: {choice}.")
    explanation, model = llm.polish(line, "Rewrite as one clear sentence for a factory owner on WhatsApp.")
    return {"gap": gap, "invoice": inv, "buyer": buyer, "pay_date": pay_date, "days_needed": days_needed,
            "choice": choice, "costs": costs, "quote": quote, "explanation": explanation, "model": model}
