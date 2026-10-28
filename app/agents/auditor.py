"""Agent 2 - Invoice Readiness Auditor: catch rejection reasons before the buyer does.

Rules first (fast, explainable, testable), then Gemini for subtler issues
against the buyer's playbook. Flags automatically; fixes need owner approval.
"""
from pydantic import BaseModel

from app import llm
from app.db import Buyer, Invoice, PurchaseOrder
from app.tools.finance import inr

AGENT = "Readiness Auditor"


class ExtraFindings(BaseModel):
    issues: list[str] = []


def rule_check(inv: Invoice, buyer: Buyer, po_lines: list[PurchaseOrder], udyam_no: str = "") -> list[dict]:
    issues = []
    if not inv.po_number:
        issues.append({"code": "missing_po", "message": "No PO number on the invoice",
                       "fix": "Add the buyer's PO number"})
    elif not po_lines:
        issues.append({"code": "unknown_po", "message": f"PO {inv.po_number} not found in our records",
                       "fix": "Check the PO number with the buyer"})
    else:
        line = next((l for l in po_lines if l.line_no == inv.po_line), None)
        right = next((l for l in po_lines if l.item == inv.item), None)
        if inv.po_line is None:
            issues.append({"code": "missing_po_line",
                           "message": "PO line number missing",
                           "fix": f"Quote PO line {right.line_no}" if right else "Quote the PO line",
                           "correct_line": right.line_no if right else None})
        elif line is None or (inv.item and line.item != inv.item):
            issues.append({"code": "po_line_mismatch",
                           "message": f"Invoice cites PO line {inv.po_line}, but '{inv.item}' is on "
                                      f"PO line {right.line_no if right else '?'}",
                           "fix": f"Change PO line {inv.po_line} -> {right.line_no}" if right else "Fix PO line",
                           "correct_line": right.line_no if right else None})
        if right and inv.qty > right.qty:
            issues.append({"code": "qty_exceeds_po",
                           "message": f"Quantity {inv.qty} exceeds PO quantity {right.qty}",
                           "fix": "Split the invoice or get a PO amendment"})
    if inv.billing_gstin and inv.billing_gstin != buyer.gstin:
        issues.append({"code": "wrong_gstin",
                       "message": f"Billed to GSTIN {inv.billing_gstin}; buyer's GSTIN is {buyer.gstin}",
                       "fix": f"Re-issue to {buyer.gstin}"})
    if not inv.udyam_printed:
        issues.append({"code": "udyam_missing",
                       "message": "Udyam number and MSE status not printed on the invoice",
                       "fix": f"Print Udyam no. {udyam_no or '(supplier Udyam)'} and category",
                       })
    if inv.sent_to and inv.sent_to.lower() != buyer.ap_email.lower():
        issues.append({"code": "wrong_recipient",
                       "message": f"Sent to {inv.sent_to}, not to AP ({buyer.ap_email})",
                       "fix": f"Send to {buyer.ap_contact} at {buyer.ap_email}"})
    if "grn" in (buyer.playbook or "").lower() and not inv.grn_no and inv.state not in ("DRAFT", "AUDITED"):
        issues.append({"code": "missing_grn", "message": "Buyer playbook needs the GRN number quoted",
                       "fix": "Add GRN reference from the delivery"})
    return issues


def audit(dossier: dict) -> tuple[list[dict], str]:
    """Returns (issues, model_used)."""
    inv, buyer = dossier["invoice"], dossier["buyer"]
    issues = rule_check(inv, buyer, dossier["po_lines"], dossier["supplier"].udyam_no)
    model = "rules"
    if buyer.playbook and llm.config.llm_online():
        prompt = (
            "You audit an Indian MSME's B2B tax invoice before it reaches the buyer's AP team.\n"
            f"Buyer playbook (what this buyer needs before paying): {buyer.playbook}\n"
            f"Invoice: no {inv.id}, date {inv.invoice_date}, amount {inv.amount}, item '{inv.item}', "
            f"PO {inv.po_number} line {inv.po_line}, qty {inv.qty}, GRN {inv.grn_no}, IRN {inv.irn}, "
            f"Udyam printed {inv.udyam_printed}, billed GSTIN {inv.billing_gstin}.\n"
            f"Issues already found by rules: {[i['message'] for i in issues]}\n"
            "List only ADDITIONAL concrete issues that would make this buyer hold payment. "
            "Return an empty list if there are none. Do not repeat the issues already found."
        )
        extra, model = llm.ask("reason", prompt, ExtraFindings, fallback=lambda: ExtraFindings())
        for msg in extra.issues[:3]:
            issues.append({"code": "llm_flag", "message": msg, "fix": "Review and correct"})
    return issues, model


def apply_fixes(inv: Invoice, buyer: Buyer, issues: list[dict]) -> list[str]:
    """Apply the fixes the owner approved. Returns a list of what changed."""
    changes = []
    for i in issues:
        c = i["code"]
        if c in ("po_line_mismatch", "missing_po_line") and i.get("correct_line"):
            changes.append(f"PO line {inv.po_line} -> {i['correct_line']}")
            inv.po_line = i["correct_line"]
        elif c == "wrong_gstin":
            changes.append(f"GSTIN {inv.billing_gstin} -> {buyer.gstin}")
            inv.billing_gstin = buyer.gstin
        elif c == "udyam_missing":
            inv.udyam_printed = True
            changes.append("Udyam number + MSE category printed")
        elif c == "wrong_recipient":
            changes.append(f"Recipient {inv.sent_to} -> {buyer.ap_email}")
            inv.sent_to = buyer.ap_email
        elif c == "missing_grn" and not inv.grn_no:
            inv.grn_no = f"GRN-{inv.id}"
            changes.append(f"GRN reference {inv.grn_no} added")
    inv.blocker = None
    return changes


def fix_draft(dossier: dict, issues: list[dict], resubmit: bool) -> str:
    inv, buyer, sup = dossier["invoice"], dossier["buyer"], dossier["supplier"]
    fixes = "\n".join(f"- {i['message']} -> {i['fix']}" for i in issues)
    if resubmit:
        intro = (f"Dear {buyer.ap_contact},\n\nPlease find the corrected invoice #{inv.id} "
                 f"({inr(inv.outstanding)}) for PO {inv.po_number}. ")
    else:
        intro = f"Dear {buyer.ap_contact},\n\nPlease find invoice #{inv.id} ({inr(inv.amount)}) for PO {inv.po_number}. "
    body = (intro + "Supporting documents (PO, GRN, e-way bill, POD) are attached and match your PO.\n\n"
            f"Regards,\nAccounts, {sup.name}\nUdyam: {sup.udyam_no} ({sup.udyam_category}, {sup.activity})")
    return f"CORRECTIONS\n{fixes}\n\nCOVER NOTE TO AP\n{body}"
