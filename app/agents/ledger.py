"""Agent 1 - Ledger & Dossier: one source of truth per invoice.

Joins invoice + PO + GRN + IRN + POD + buyer + replies + payments into a
single 'dossier' dict that every other agent reads. Pure code; the vision
model is only used when a POD photo is uploaded (llm.describe_image).
"""
from datetime import date

from sqlmodel import select

from app import config
from app import mocks
from app.db import BankTxn, Buyer, Invoice, PurchaseOrder, Reply, Supplier
from app.state_machine import log
from app.tools.finance import ageing_bucket, invoice_age, sec16_interest

AGENT = "Ledger & Dossier"


def build(session, inv: Invoice, today: date | None = None) -> dict:
    today = today or config.today()
    buyer = session.get(Buyer, inv.buyer_id)
    supplier = session.get(Supplier, 1)
    po_lines = session.exec(select(PurchaseOrder).where(PurchaseOrder.po_number == inv.po_number)).all() \
        if inv.po_number else []
    replies = session.exec(select(Reply).where(Reply.invoice_id == inv.id)
                           .order_by(Reply.received_at)).all()
    age = invoice_age(inv.invoice_date, today)
    days_late = max(0, age - 45)
    return {
        "invoice": inv,
        "buyer": buyer,
        "supplier": supplier,
        "po_lines": po_lines,
        "replies": replies,
        "irn": mocks.irn_lookup(inv),
        "age": age,
        "bucket": ageing_bucket(age),
        "due_in": min(buyer.credit_days, 45) - age,
        "statutory_days_left": 45 - age,
        "interest_accrued": sec16_interest(inv.outstanding, days_late),
        "today": today,
    }


def match_payments(session, today: date | None = None) -> list[str]:
    """Auto-match unmatched bank credits to open invoices (by invoice number in
    the narration, else exact amount). Returns ids of invoices marked PAID."""
    from app.state_machine import move, can_move
    paid = []
    credits = session.exec(select(BankTxn).where(BankTxn.matched_invoice == None)).all()  # noqa: E711
    for txn in credits:
        target = None
        for inv in session.exec(select(Invoice).where(Invoice.state != "PAID")).all():
            if inv.id in txn.narration or abs(inv.outstanding - txn.amount) < 1:
                target = inv
                break
        if not target:
            continue
        txn.matched_invoice = target.id
        target.paid_amount = round(target.paid_amount + txn.amount, 2)
        session.add(txn)
        if target.outstanding <= 1 and can_move(target, "PAID"):
            target.paid_date = txn.txn_date
            move(session, target, "PAID", AGENT, "match_payment",
                 detail=f"Bank credit {txn.amount:,.0f} matched", evidence=f"AA feed: {txn.narration}")
            paid.append(target.id)
        else:
            log(session, target.id, AGENT, "match_payment",
                detail=f"Part payment {txn.amount:,.0f} received", evidence=f"AA feed: {txn.narration}",
                state=target.state)
        session.add(target)
    return paid
