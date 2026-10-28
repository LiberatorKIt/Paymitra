"""Carries out an action. The only place where anything leaves PayMitra.

Guardrail: an action whose autonomy is not 'auto' is refused unless an
approval row says the owner approved it. This is tested in tests/eval_agents.py.
"""
import json
from datetime import date, datetime

from sqlmodel import select

from app import config
from app import mocks, whatsapp
from app.agents import auditor, buyer_intel, escalation, ledger
from app.db import Approval, Buyer, Invoice, PurchaseOrder, Supplier
from app.state_machine import AUTONOMY, autonomy_for, can_move, log, move
from app.tools.finance import inr


class GuardrailError(PermissionError):
    pass


def check_permission(action: str, buyer: Buyer, approval: Approval | None) -> None:
    level = autonomy_for(action, buyer)
    if level == "auto":
        return
    if approval is None or approval.status not in ("APPROVED", "EDITED") or approval.action != action:
        raise GuardrailError(f"'{action}' needs the owner's approval before it can run")


def execute(session, inv: Invoice, action: str, draft: str = "", payload: dict | None = None,
            approval: Approval | None = None, today: date | None = None) -> str:
    """Run one action. Returns a one-line result for the owner."""
    today = today or config.today()
    payload = payload or {}
    buyer = session.get(Buyer, inv.buyer_id)
    check_permission(action, buyer, approval)
    model = payload.get("model", "code")
    name, email = buyer_intel.contact_for(action, buyer)

    if action == "audit":  # passed the audit -> send to the right AP inbox
        move(session, inv, "AUDITED", auditor.AGENT, "audit", detail="No issues found", model=model)
        inv.sent_to = buyer.ap_email
        move(session, inv, "SENT", auditor.AGENT, "send", detail=f"Sent to {buyer.ap_email}")
        whatsapp.send_buyer(session, inv.id, buyer.ap_email, f"Invoice #{inv.id}", draft or f"Invoice #{inv.id} attached.")
        result = f"Invoice #{inv.id} passed the audit and was sent to {buyer.ap_contact} (AP)."

    elif action in ("fix_invoice", "send_fix"):
        issues = payload.get("issues") or []
        changes = auditor.apply_fixes(inv, buyer, issues)
        if action == "fix_invoice":
            move(session, inv, "AUDITED", auditor.AGENT, "fix_invoice", detail="; ".join(changes), model=model)
            move(session, inv, "SENT", auditor.AGENT, "send", detail=f"Sent to {buyer.ap_email}")
            result = f"Fixed and sent #{inv.id} to {buyer.ap_contact}: {'; '.join(changes)}."
        else:
            move(session, inv, "FIX_AND_RESUBMIT", auditor.AGENT, "send_fix", detail="; ".join(changes), model=model)
            move(session, inv, "SENT", auditor.AGENT, "resubmit", detail="Corrected invoice uploaded",
                 evidence="Vendor portal upload (mock)")
            rec = mocks.resubmit(session, inv)
            if can_move(inv, "ACKNOWLEDGED"):
                move(session, inv, "ACKNOWLEDGED", buyer_intel.AGENT, "receipt_check",
                     detail=f"Portal: {rec.status}" + (f", payment run {rec.payment_run:%d %b}" if rec.payment_run else ""),
                     evidence="Vendor portal status (mock)")
            run = f" Their next payment run is {rec.payment_run:%d %b}." if rec.payment_run else ""
            result = f"Sent and uploaded corrected #{inv.id} to {buyer.name}.{run}"
        whatsapp.send_buyer(session, inv.id, buyer.ap_email, f"Corrected invoice #{inv.id}", draft)
        for i in issues:
            if i["code"] in ("po_line_mismatch", "missing_po_line"):
                buyer_intel.learn(session, inv, "Quote the PO line exactly as on the PO.")
            if i["code"] == "wrong_recipient":
                buyer_intel.learn(session, inv, f"Invoices go to AP ({buyer.ap_email}), not sales.")

    elif action == "receipt_check":
        move(session, inv, "ACKNOWLEDGED", buyer_intel.AGENT, "receipt_check",
             detail="Buyer AP has logged the invoice", evidence="Vendor portal / AP inbox (mock)")
        result = f"#{inv.id} confirmed received by {buyer.name}."

    elif action in ("pre_due_nudge", "reminder", "answer_query", "note_43bh", "voice_call"):
        channel = "voice" if action == "voice_call" else "email"
        subject = {"pre_due_nudge": f"Invoice #{inv.id} - due soon", "reminder": f"Invoice #{inv.id} - payment date?",
                   "answer_query": f"Re: invoice #{inv.id}", "note_43bh": f"Invoice #{inv.id} - 43B(h) timeline",
                   "voice_call": f"Call to {name}"}[action]
        whatsapp.send_buyer(session, inv.id, email if channel == "email" else buyer.phone, subject, draft, channel)
        log(session, inv.id, "Follow-up Negotiator", action, detail=f"{subject} -> {name}",
            evidence=f"Outbox ({channel})", model=model, state=inv.state)
        if action == "answer_query" and inv.state == "DISPUTED":
            inv.blocker = None
            move(session, inv, "FIX_AND_RESUBMIT", "Follow-up Negotiator", "answer_query",
                 detail="Clarification / credit note sent")
            move(session, inv, "SENT", "Follow-up Negotiator", "resubmit", detail="Re-sent with documents")
        result = f"{subject} sent to {name}."

    elif action == "finance_treds":
        cost = float(payload["costs"]["TREDS"])
        txn = mocks.treds_finance(session, inv, cost)
        inv.financed_amount = txn.amount
        move(session, inv, "FINANCED", "Cash & Finance Optimiser", "finance_treds",
             detail=f"TReDS: received {inr(txn.amount)} today (discount {inr(cost)})",
             evidence="TReDS platform (mock)", model=model)
        result = f"#{inv.id} financed on TReDS: {inr(txn.amount)} credited today, cost {inr(cost)}."

    elif action == "draw_od":
        log(session, inv.id, "Cash & Finance Optimiser", "draw_od",
            detail=f"Owner approved OD drawdown {inr(payload.get('amount', 0))}", state=inv.state)
        result = "Overdraft drawdown noted for your bank."

    elif action == "formal_notice":
        whatsapp.send_buyer(session, inv.id, buyer.finance_email, f"Notice: invoice #{inv.id}", draft)
        if can_move(inv, "ESCALATION_READY"):
            move(session, inv, "ESCALATION_READY", escalation.AGENT, "formal_notice",
                 detail="Sec 15/16 notice sent", evidence="Outbox (email)")
        result = f"Formal notice sent to {buyer.finance_head}."

    elif action == "odr_pack":
        if can_move(inv, "ESCALATION_READY"):
            move(session, inv, "ESCALATION_READY", escalation.AGENT, "odr_pack", detail="ODR pack prepared")
        else:
            log(session, inv.id, escalation.AGENT, "odr_pack", detail="ODR pack prepared", state=inv.state)
        result = f"ODR pack for #{inv.id} is ready to review and file."
    else:
        raise ValueError(f"Unknown action {action}")

    inv.add_action(action)
    session.add(inv)
    if approval is not None:
        approval.status = "DONE"
        session.add(approval)
    return result
