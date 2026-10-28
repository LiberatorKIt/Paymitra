"""Mock versions of the outside systems PayMitra talks to.

Each function has the same shape a real integration would have, so going live
means replacing the body of one function (or pointing it at a real URL),
not changing any agent. The same mocks are also exposed over HTTP under /mock
so the jury can see the 'outside world' the agents are reading.
"""
from datetime import date, timedelta

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlmodel import select

from app import config
from app.db import BankTxn, Buyer, Invoice, PortalRecord, PurchaseOrder, Supplier, get_session
from app.tools.finance import treds_cost


def today() -> date:
    return config.today()


def next_payment_run(day_of_month: int, after: date) -> date:
    day_of_month = max(1, min(day_of_month, 28))
    d = after + timedelta(days=1)
    for _ in range(62):
        if d.day == day_of_month:
            return d
        d += timedelta(days=1)
    return after + timedelta(days=30)


# --- What a buyer's AP system / vendor portal would say about an invoice ---------
def _derive_ap_status(session, inv: Invoice, buyer: Buyer) -> tuple[str, str]:
    if inv.state in ("DRAFT", "AUDITED"):
        return "NOT_SUBMITTED", ""
    if inv.state == "PAID":
        return "PAID", ""
    if inv.sent_to and inv.sent_to.lower() != buyer.ap_email.lower():
        return "NOT_RECEIVED", f"AP has no record - invoice was emailed to {inv.sent_to}"
    if inv.billing_gstin and inv.billing_gstin != buyer.gstin:
        return "ON_HOLD", f"GSTIN mismatch: billed to {inv.billing_gstin}, registered {buyer.gstin}"
    if buyer.has_portal:
        if not inv.po_number:
            return "ON_HOLD", "No PO reference on invoice"
        lines = session.exec(select(PurchaseOrder).where(PurchaseOrder.po_number == inv.po_number)).all()
        match = next((l for l in lines if l.line_no == inv.po_line), None)
        if match is None or (inv.item and match.item != inv.item):
            right = next((l for l in lines if l.item == inv.item), None)
            hint = f" (item is on PO line {right.line_no})" if right else ""
            return "ON_HOLD", f"PO line mismatch: invoice cites line {inv.po_line}{hint}"
    return "LOGGED", ""


def ap_status(session, inv: Invoice) -> PortalRecord:
    """Buyer Intelligence calls this (a browser agent / AP email check in real life)."""
    rec = session.get(PortalRecord, inv.id)
    if rec is not None:
        return rec
    buyer = session.get(Buyer, inv.buyer_id)
    status, reason = _derive_ap_status(session, inv, buyer)
    run = None
    if status == "LOGGED" and buyer.payment_run_day:
        due = inv.invoice_date + timedelta(days=45)
        run = next_payment_run(buyer.payment_run_day, max(today(), due - timedelta(days=1)))
    rec = PortalRecord(invoice_id=inv.id, status=status, reason=reason, payment_run=run)
    if status not in ("NOT_SUBMITTED",):
        session.add(rec)
    return rec


def resubmit(session, inv: Invoice) -> PortalRecord:
    """Upload the corrected invoice to the portal / AP inbox."""
    buyer = session.get(Buyer, inv.buyer_id)
    run = next_payment_run(buyer.payment_run_day, today()) if buyer.payment_run_day else None
    rec = session.get(PortalRecord, inv.id) or PortalRecord(invoice_id=inv.id, status="APPROVED")
    rec.status, rec.reason, rec.payment_run = "APPROVED", "Corrected invoice accepted", run
    session.add(rec)
    return rec


def irn_lookup(inv: Invoice) -> dict:
    """GST e-invoice (IRN) check."""
    if inv.irn:
        return {"irn": inv.irn, "status": "ACTIVE", "ack_date": str(inv.invoice_date)}
    return {"irn": None, "status": "NOT_FOUND"}


def udyam_verify(udyam_no: str, session=None) -> dict:
    """Udyam registration check (category decides whether 43B(h) applies)."""
    with get_session() as s:
        sup = s.get(Supplier, 1)
    if sup and udyam_no == sup.udyam_no:
        return {"udyam_no": udyam_no, "valid": True, "category": sup.udyam_category,
                "activity": sup.activity}
    return {"udyam_no": udyam_no, "valid": False}


def treds_quote(buyer: Buyer, amount: float, days: int) -> dict:
    if not buyer.on_treds:
        return {"available": False, "reason": f"{buyer.name} is not on a TReDS platform"}
    return {"available": True, "platform": "TReDS (mock)", "amount": amount, "days": days,
            "cost": treds_cost(amount, days)}


def treds_finance(session, inv: Invoice, cost: float) -> BankTxn:
    net = round(inv.outstanding - cost, 2)
    txn = BankTxn(txn_date=today(), amount=net,
                  narration=f"TREDS FINANCE INV {inv.id} NET OF DISCOUNT",
                  matched_invoice=inv.id, live=True)
    session.add(txn)
    return txn


def aa_bank_feed(session, since: date | None = None) -> list[BankTxn]:
    """Account Aggregator bank feed: the credits the bank reports."""
    q = select(BankTxn)
    if since:
        q = q.where(BankTxn.txn_date >= since)
    return list(session.exec(q.order_by(BankTxn.txn_date.desc())).all())


ODR_CHECKLIST = [
    "Udyam registration certificate (micro / small category)",
    "Purchase order and any agreement on credit terms",
    "Tax invoice(s) with GST IRN and e-way bill",
    "Proof of delivery / GRN / acceptance by buyer",
    "Ledger extract showing amounts outstanding",
    "Copies of reminders and the Sec 15/16 notice with delivery proof",
    "Statement of interest under Sec 16 (computed)",
]


# --- HTTP view of the mocks (for demos and for future real swaps) -------------
router = APIRouter(prefix="/mock", tags=["mock integrations"])


@router.get("/portal/{invoice_id}")
def http_portal(invoice_id: str):
    with get_session() as s:
        inv = s.get(Invoice, invoice_id)
        if not inv:
            return {"error": "unknown invoice"}
        rec = ap_status(s, inv)
        s.commit()
        return {"invoice": invoice_id, "status": rec.status, "reason": rec.reason,
                "payment_run": rec.payment_run}


@router.get("/portal-ui/{invoice_id}", response_class=HTMLResponse)
def http_portal_ui(invoice_id: str):
    """A tiny fake vendor portal page (what a browser agent would read)."""
    data = http_portal(invoice_id)
    colour = {"ON_HOLD": "#b54708", "APPROVED": "#067647", "LOGGED": "#175cd3"}.get(data.get("status"), "#444")
    return f"""<html><body style="font-family:system-ui;padding:32px;max-width:640px">
    <h2>Buyer Vendor Portal (mock)</h2><p>Invoice <b>{invoice_id}</b></p>
    <p>Status: <b style="color:{colour}">{data.get('status')}</b></p>
    <p>{data.get('reason') or ''}</p><p>Next payment run: {data.get('payment_run') or '-'}</p>
    </body></html>"""


@router.get("/irn/{invoice_id}")
def http_irn(invoice_id: str):
    with get_session() as s:
        inv = s.get(Invoice, invoice_id)
        return irn_lookup(inv) if inv else {"error": "unknown invoice"}


@router.get("/udyam/{udyam_no}")
def http_udyam(udyam_no: str):
    return udyam_verify(udyam_no)


@router.get("/treds/quote")
def http_treds(buyer_id: str, amount: float, days: int):
    with get_session() as s:
        b = s.get(Buyer, buyer_id)
        return treds_quote(b, amount, days) if b else {"error": "unknown buyer"}


@router.get("/aa/transactions")
def http_aa():
    with get_session() as s:
        return aa_bank_feed(s, today() - timedelta(days=30))


@router.get("/odr/checklist")
def http_odr():
    return {"portal": "MSME ODR (mock)", "checklist": ODR_CHECKLIST}
