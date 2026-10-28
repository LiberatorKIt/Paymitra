"""The invoice state machine and the autonomy policy.

This is code, not a prompt: an LLM can only ever choose among the moves
allowed here, and every move writes an audit-log row with its evidence.
"""
from app.db import AuditLog, Buyer, Invoice

TRANSITIONS: dict[str, list[str]] = {
    "DRAFT":            ["AUDITED"],
    "AUDITED":          ["SENT", "DRAFT"],
    "SENT":             ["ACKNOWLEDGED", "FIX_AND_RESUBMIT", "DUE", "PAID"],
    "ACKNOWLEDGED":     ["DUE", "FIX_AND_RESUBMIT", "PROMISED", "DISPUTED", "PAID", "FINANCED"],
    "DUE":              ["PROMISED", "DISPUTED", "SILENT", "PAID", "FINANCED",
                         "FIX_AND_RESUBMIT", "ESCALATION_READY"],
    "PROMISED":         ["PAID", "FIX_AND_RESUBMIT", "ESCALATION_READY", "FINANCED",
                         "DISPUTED", "SILENT"],
    "DISPUTED":         ["FIX_AND_RESUBMIT", "ESCALATION_READY", "PROMISED", "PAID"],
    "SILENT":           ["PROMISED", "DISPUTED", "PAID", "ESCALATION_READY", "FINANCED"],
    "FIX_AND_RESUBMIT": ["SENT"],
    "ESCALATION_READY": ["PAID", "FINANCED", "ODR_FILED", "PROMISED"],
    "FINANCED":         ["PAID"],
    "ODR_FILED":        ["PAID"],
    "PAID":             [],
}

CLOSED_STATES = {"PAID", "FINANCED", "ODR_FILED"}

# auto    = agent acts alone
# approve = agent proposes, owner taps Approve (WhatsApp or website)
# owner   = only the owner can start it; the agent prepares everything
AUTONOMY: dict[str, str] = {
    "audit": "auto",
    "receipt_check": "auto",
    "pre_due_nudge": "auto",
    "reminder": "auto",
    "classify_reply": "auto",
    "match_payment": "auto",
    "fix_invoice": "approve",     # a new invoice the auditor stopped
    "send_fix": "approve",        # corrected invoice for one stuck at the buyer
    "answer_query": "approve",
    "voice_call": "approve",
    "note_43bh": "approve",
    "finance_treds": "approve",
    "draw_od": "approve",
    "formal_notice": "owner",
    "odr_pack": "owner",
}

ACTION_LABELS = {
    "audit": "Readiness audit",
    "receipt_check": "Receipt check",
    "pre_due_nudge": "Pre-due nudge",
    "reminder": "Reminder",
    "fix_invoice": "Fix invoice before sending",
    "send_fix": "Send corrected invoice",
    "answer_query": "Answer buyer query",
    "voice_call": "Voice call to AP",
    "note_43bh": "43B(h) note to finance head",
    "finance_treds": "Finance via TReDS",
    "draw_od": "Draw on overdraft",
    "formal_notice": "Formal Sec 15/16 notice",
    "odr_pack": "Prepare ODR filing pack",
}


class TransitionError(ValueError):
    pass


def autonomy_for(action: str, buyer: Buyer | None) -> str:
    level = AUTONOMY.get(action, "approve")
    # Relationship-safe by design: a "sensitive" buyer never gets an automatic message.
    if buyer is not None and buyer.sensitive and level == "auto" and action in {"pre_due_nudge", "reminder"}:
        return "approve"
    return level


def can_move(invoice: Invoice, new_state: str) -> bool:
    return new_state in TRANSITIONS.get(invoice.state, [])


def move(session, invoice: Invoice, new_state: str, agent: str, action: str,
         detail: str = "", evidence: str = "", model: str = "code") -> None:
    if invoice.state == new_state:
        return
    if not can_move(invoice, new_state):
        raise TransitionError(f"Invoice {invoice.id}: {invoice.state} -> {new_state} is not allowed")
    session.add(AuditLog(invoice_id=invoice.id, agent=agent, action=action,
                         from_state=invoice.state, to_state=new_state,
                         detail=detail, evidence=evidence, model=model))
    invoice.state = new_state
    session.add(invoice)


def log(session, invoice_id: str, agent: str, action: str, detail: str = "",
        evidence: str = "", model: str = "code", state: str = "") -> None:
    """An audit row without a state change (e.g. 'reminder sent')."""
    session.add(AuditLog(invoice_id=invoice_id, agent=agent, action=action,
                         from_state=state, to_state=state,
                         detail=detail, evidence=evidence, model=model))
