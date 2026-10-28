"""Read-side helpers: KPIs and JSON shapes the website uses."""
import json
from datetime import date, timedelta

from sqlmodel import select

from app import config
from app.agents import buyer_intel, cash_optimiser
from app.db import Approval, Buyer, Invoice, PortalRecord, Supplier
from app.state_machine import ACTION_LABELS, AUTONOMY
from app.tools.finance import ageing_bucket, invoice_age

OPEN_EXCLUDE = {"DRAFT", "AUDITED", "PAID", "FINANCED", "ODR_FILED"}


def due_date(inv: Invoice, buyer: Buyer) -> date:
    return inv.invoice_date + timedelta(days=min(buyer.credit_days, 45))


def kpis(s, today: date | None = None) -> dict:
    today = today or config.today()
    sup = s.get(Supplier, 1)
    buyers = {b.id: b for b in s.exec(select(Buyer)).all()}
    invs = s.exec(select(Invoice)).all()
    open_invs = [i for i in invs if i.state not in OPEN_EXCLUDE]
    outstanding = sum(i.outstanding for i in open_invs)
    beyond = sum(i.outstanding for i in open_invs if invoice_age(i.invoice_date, today) > 45)
    due_week = sum(i.outstanding for i in open_invs
                   if today <= due_date(i, buyers[i.buyer_id]) <= today + timedelta(days=7))
    stuck = [i for i in invs if i.blocker and i.state not in ("PAID", "FINANCED", "DRAFT", "AUDITED")]
    recent_paid = [i for i in invs if i.state == "PAID" and i.paid_date and (today - i.paid_date).days <= 180]
    paid_val = sum(i.amount for i in recent_paid) or 1
    within = sum(i.amount for i in recent_paid if (i.paid_date - i.invoice_date).days <= 45)
    by_state: dict[str, int] = {}
    for i in invs:
        by_state[i.state] = by_state.get(i.state, 0) + 1
    fc = cash_optimiser.forecast(s, today)
    return {
        "owner": sup.owner_name, "supplier": sup.name, "today": today,
        "outstanding": round(outstanding, 2), "open_count": len(open_invs),
        "beyond_45": round(beyond, 2), "beyond_45_pct": round(100 * beyond / outstanding, 1) if outstanding else 0,
        "due_this_week": round(due_week, 2),
        "stuck_count": len(stuck), "stuck_value": round(sum(i.outstanding for i in stuck), 2),
        "collected_within_45_pct": round(100 * within / paid_val, 1),
        "pending_approvals": len(s.exec(select(Approval).where(Approval.status == "PENDING")).all()),
        "by_state": by_state, "gap": fc["first_gap"],
        "llm_mode": "online" if config.llm_online() else "offline",
        "gemini": bool(config.GEMINI_API_KEY), "nemotron": bool(config.NVIDIA_API_KEY),
        "twilio": config.twilio_ready(),
    }


def invoice_row(s, inv: Invoice, buyer: Buyer, today: date) -> dict:
    age = invoice_age(inv.invoice_date, today)
    rec = s.get(PortalRecord, inv.id)
    exp = buyer_intel.predict(s, inv, buyer, today)
    return {
        "id": inv.id, "buyer_id": buyer.id, "buyer": buyer.name, "persona": buyer.persona,
        "invoice_date": inv.invoice_date, "due_date": due_date(inv, buyer), "age": age,
        "bucket": ageing_bucket(age), "amount": inv.amount, "outstanding": inv.outstanding,
        "state": inv.state, "blocker": inv.blocker, "last_action": ACTION_LABELS.get(inv.last_action, inv.last_action),
        "portal": rec.status if rec else None, "expected": exp[0]["date"] if exp else None,
        "promises": inv.get_promises(), "sensitive": buyer.sensitive,
    }


def approval_view(a: Approval) -> dict:
    return {
        "id": a.id, "invoice_id": a.invoice_id, "action": a.action, "title": a.title, "reason": a.reason,
        "draft": a.draft, "payload": json.loads(a.payload or "{}"), "autonomy": a.autonomy,
        "status": a.status, "created_at": a.created_at, "decided_at": a.decided_at, "decided_via": a.decided_via,
        "label": ACTION_LABELS.get(a.action, a.action),
    }


AUTONOMY_TABLE = [{"action": k, "label": ACTION_LABELS.get(k, k), "level": v} for k, v in AUTONOMY.items()]
