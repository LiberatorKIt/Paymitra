"""Agent 3 - Buyer Intelligence: where is the invoice at the buyer, and when will they pay?

Reads the buyer's AP status (vendor portal / AP inbox mock) and predicts the
pay date from the buyer's own history. Pure code in the MVP; a browser agent
and a learned model can replace these functions later.
"""
import json
from datetime import date, timedelta

from app import config
from app import mocks
from app.db import Buyer, Invoice, PortalRecord
from app.state_machine import CLOSED_STATES, log

AGENT = "Buyer Intelligence"


def check_ap(session, dossier: dict) -> PortalRecord:
    inv: Invoice = dossier["invoice"]
    rec = mocks.ap_status(session, inv)
    if rec.status in ("ON_HOLD", "NOT_RECEIVED"):
        if inv.blocker != rec.reason:
            inv.blocker = rec.reason
            session.add(inv)
            log(session, inv.id, AGENT, "portal_check", detail=f"{rec.status}: {rec.reason}",
                evidence=f"Vendor portal / AP status for #{inv.id}", state=inv.state)
    return rec


def predict(session, inv: Invoice, buyer: Buyer, today: date | None = None) -> list[dict]:
    """Expected receipts for one invoice: [{'date', 'amount', 'basis'}]."""
    today = today or config.today()
    if inv.state in CLOSED_STATES or inv.state in ("DRAFT", "AUDITED") or inv.outstanding <= 0:
        return []
    if inv.blocker or inv.state == "DISPUTED":
        return []   # stuck: nothing will come until it is fixed
    promises = inv.get_promises()
    if promises:
        out = []
        for p in promises:
            d = date.fromisoformat(p["date"])
            if d < today:
                d = today + timedelta(days=max(7, buyer.slip_days // 2))
            out.append({"date": d, "amount": float(p["amount"]), "basis": "buyer promise"})
        return out
    rec = session.get(PortalRecord, inv.id)
    if rec and rec.payment_run:
        return [{"date": rec.payment_run + timedelta(days=buyer.slip_days), "amount": inv.outstanding,
                 "basis": f"payment run {rec.payment_run} + usual slip {buyer.slip_days}d"}]
    d = inv.invoice_date + timedelta(days=round(buyer.avg_days_to_pay))
    if d <= today:
        d = today + timedelta(days=max(7, buyer.slip_days))
    return [{"date": d, "amount": inv.outstanding, "basis": f"history: avg {buyer.avg_days_to_pay:.0f} days"}]


def contact_for(action: str, buyer: Buyer) -> tuple[str, str]:
    """Right person, right lever: AP clerk for status, finance head for 43B(h)."""
    if action in ("note_43bh", "formal_notice"):
        return buyer.finance_head, buyer.finance_email
    return buyer.ap_contact, buyer.ap_email


def learn(session, inv: Invoice, lesson: str) -> None:
    """Update the buyer playbook (the moat: what each buyer needs before it pays)."""
    buyer = session.get(Buyer, inv.buyer_id)
    if lesson and lesson not in (buyer.playbook or ""):
        buyer.playbook = (buyer.playbook + " " if buyer.playbook else "") + lesson
        session.add(buyer)
        log(session, inv.id, AGENT, "playbook_update", detail=lesson, state=inv.state)


def promises_json(promises: list[dict]) -> str:
    return json.dumps(promises, default=str)
