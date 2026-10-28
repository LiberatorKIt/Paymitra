"""PayMitra web server: JSON API + the website + WhatsApp webhook, in one process.

Run locally:   uvicorn app.main:app --reload
Then open:     http://localhost:8000
"""
import csv
import hashlib
import hmac
import io
import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import select

from app import config, mocks, whatsapp
from app.agents import cash_optimiser, escalation, ledger, negotiator, orchestrator
from app.api_views import AUTONOMY_TABLE, approval_view, invoice_row, kpis
from app.db import (Approval, AuditLog, BankTxn, Buyer, Invoice, Message, Reply, Supplier, get_session,
                    init_db, is_empty, reset_db)
from app.executor import GuardrailError, execute
from app.state_machine import ACTION_LABELS, TRANSITIONS, TransitionError, log, move
from app.tools.finance import inr

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if config.SEED_IF_EMPTY and is_empty():
        from app.seed import seed
        seed()
    yield


app = FastAPI(title="PayMitra", description="AI receivables officer for India's MSMEs", version="1.0",
              lifespan=lifespan)


# ------------------------------------------------------------------ login (optional)
def _token() -> str:
    return hmac.new(config.SECRET_KEY.encode(), config.APP_PASSWORD.encode(), hashlib.sha256).hexdigest()


OPEN_PATHS = ("/login", "/api/login", "/api/whatsapp/webhook", "/health", "/styles.css", "/favicon.svg")


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if not config.APP_PASSWORD or path.startswith(OPEN_PATHS):
        return await call_next(request)
    if path == "/api/cycle" and config.CYCLE_TOKEN and request.headers.get("x-cycle-token") == config.CYCLE_TOKEN:
        return await call_next(request)
    if hmac.compare_digest(request.cookies.get("pm_auth", ""), _token()):
        return await call_next(request)
    if path.startswith("/api") or path.startswith("/mock"):
        return JSONResponse({"detail": "Login required"}, status_code=401)
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return (WEB_DIR / "login.html").read_text(encoding="utf-8")


@app.post("/api/login")
def login(payload: dict = Body(...)):
    if not config.APP_PASSWORD or not hmac.compare_digest(payload.get("password", ""), config.APP_PASSWORD):
        raise HTTPException(401, "Wrong password")
    resp = JSONResponse({"ok": True})
    resp.set_cookie("pm_auth", _token(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 14,
                    secure=config.PUBLIC_BASE_URL.startswith("https"))
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("pm_auth")
    return resp


@app.get("/health")
def health():
    return {"ok": True, "llm": "online" if config.llm_online() else "offline"}


# ------------------------------------------------------------------ dashboard data
@app.get("/api/summary")
def summary():
    with get_session() as s:
        k = kpis(s)
        sup = s.get(Supplier, 1)
        k["supplier_detail"] = sup.model_dump()
        k["auth"] = bool(config.APP_PASSWORD)
        k["cycle_run_today"] = s.exec(select(AuditLog).where(AuditLog.at >= datetime.combine(config.today(), datetime.min.time()))).first() is not None
        return k


@app.get("/api/invoices")
def invoices(state: str | None = None, buyer: str | None = None, open_only: bool = False):
    today = config.today()
    with get_session() as s:
        buyers = {b.id: b for b in s.exec(select(Buyer)).all()}
        q = select(Invoice)
        if state:
            q = q.where(Invoice.state == state)
        if buyer:
            q = q.where(Invoice.buyer_id == buyer)
        rows = []
        for inv in s.exec(q).all():
            if open_only and inv.state in ("PAID", "FINANCED", "ODR_FILED"):
                continue
            rows.append(invoice_row(s, inv, buyers[inv.buyer_id], today))
        rows.sort(key=lambda r: (r["state"] == "PAID", -r["age"] if r["state"] != "PAID" else 0))
        return rows


@app.get("/api/invoices/{invoice_id}")
def invoice_detail(invoice_id: str):
    today = config.today()
    with get_session() as s:
        inv = s.get(Invoice, invoice_id)
        if not inv:
            raise HTTPException(404, "Invoice not found")
        d = ledger.build(s, inv, today)
        buyer = d["buyer"]
        row = invoice_row(s, inv, buyer, today)
        audit = s.exec(select(AuditLog).where(AuditLog.invoice_id == inv.id).order_by(AuditLog.at.desc())).all()
        approvals = s.exec(select(Approval).where(Approval.invoice_id == inv.id).order_by(Approval.id.desc())).all()
        msgs = s.exec(select(Message).where(Message.invoice_id == inv.id).order_by(Message.at.desc())).all()
        s.commit()
        return {
            **row,
            "invoice": inv.model_dump(),
            "buyer_detail": buyer.model_dump(),
            "po_lines": [p.model_dump() for p in d["po_lines"]],
            "irn": d["irn"],
            "interest": escalation.interest_statement(d),
            "replies": [r.model_dump() for r in d["replies"]],
            "audit": [a.model_dump() for a in audit],
            "approvals": [approval_view(a) for a in approvals],
            "messages": [m.model_dump() for m in msgs],
            "allowed_next": TRANSITIONS.get(inv.state, []),
        }


@app.post("/api/invoices/{invoice_id}/run")
def run_one(invoice_id: str):
    with get_session() as s:
        if not s.get(Invoice, invoice_id):
            raise HTTPException(404, "Invoice not found")
        out = orchestrator.run_invoice(s, invoice_id)
        s.commit()
        return {"action": out.get("action"), "label": ACTION_LABELS.get(out.get("action") or "", None),
                "reason": out.get("reason"), "outcome": out.get("outcome"), "model": out.get("model"),
                "approval_id": out.get("approval_id")}


@app.post("/api/cycle")
def run_cycle():
    return orchestrator.daily_cycle()


@app.get("/api/approvals")
def approvals(status: str = "PENDING"):
    with get_session() as s:
        q = select(Approval)
        if status != "ALL":
            q = q.where(Approval.status == status)
        rows = s.exec(q.order_by(Approval.id if status == "PENDING" else Approval.id.desc())).all()
        out = []
        for a in rows:
            v = approval_view(a)
            inv = s.get(Invoice, a.invoice_id)
            b = s.get(Buyer, inv.buyer_id)
            v.update(buyer=b.name, amount=inv.outstanding, state=inv.state)
            out.append(v)
        return out


def decide(approval_id: int, decision: str, draft: str | None = None, via: str = "web") -> dict:
    with get_session() as s:
        a = s.get(Approval, approval_id)
        if not a:
            raise HTTPException(404, "Approval not found")
        if a.status != "PENDING":
            return {"ok": False, "message": f"#{a.id} is already {a.status.lower()}"}
        inv = s.get(Invoice, a.invoice_id)
        if decision == "edit":
            if draft is None:
                return {"ok": True, "message": f"Edit #{a.id} on the website: {config.PUBLIC_BASE_URL}/#/approvals"}
            a.draft = draft
            s.add(a)
            log(s, inv.id, "Owner", "edit_draft", detail=f"Edited draft for {a.title}", state=inv.state)
            s.commit()
            return {"ok": True, "message": f"Draft for #{a.id} saved. Approve when ready."}
        a.decided_at, a.decided_via = config.now(), via
        if decision == "hold":
            a.status = "HELD"
            log(s, inv.id, "Owner", "hold", detail=f"Held: {a.title}", state=inv.state)
            s.add(a)
            s.commit()
            return {"ok": True, "message": f"Held #{a.id}. I will not do this unless you ask again."}
        if draft is not None and draft != a.draft:
            a.draft, a.status = draft, "EDITED"
        else:
            a.status = "APPROVED"
        try:
            result = execute(s, inv, a.action, a.draft, json.loads(a.payload or "{}"), approval=a)
        except (GuardrailError, TransitionError) as exc:
            s.rollback()
            return {"ok": False, "message": str(exc)}
        log(s, inv.id, "Owner", "approve", detail=f"Approved via {via}: {a.title}", state=inv.state)
        s.commit()
        nxt = None
        if a.action in ("send_fix", "fix_invoice", "answer_query"):
            nxt = orchestrator.propose_financing(s)
            s.commit()
        msg = "Done. " + result + (f"\n\nNext:\n{orchestrator.owner_line(nxt)}" if nxt else "")
        whatsapp.send_owner(s, msg, approval_id=nxt.id if nxt else None, invoice_id=inv.id)
        s.commit()
        return {"ok": True, "message": msg}


@app.post("/api/approvals/{approval_id}")
def decide_web(approval_id: int, payload: dict = Body(...)):
    decision = payload.get("decision")
    if decision not in ("approve", "edit", "hold"):
        raise HTTPException(400, "decision must be approve, edit or hold")
    return decide(approval_id, decision, payload.get("draft"), via="website")


# ------------------------------------------------------------------ WhatsApp
def handle_owner_text(text: str, via: str) -> str:
    decision, approval_id = whatsapp.parse_command(text)
    with get_session() as s:
        whatsapp.record_inbound(s, text)
        s.commit()
        if decision is None:
            pending = whatsapp.oldest_pending(s)
            reply = ("Reply 1 to approve, 2 to edit, 3 to hold" + (f" (next: #{pending.id} {pending.title})" if pending else "")
                     + ". Or send 'brief' for today's summary.")
            if text.strip().lower() in ("brief", "hi", "hello", "summary"):
                reply = orchestrator.send_brief(s)
                s.commit()
                return reply
            whatsapp.send_owner(s, reply)
            s.commit()
            return reply
        if approval_id is None:
            pending = whatsapp.last_offered(s) or whatsapp.oldest_pending(s)
            if not pending:
                whatsapp.send_owner(s, "Nothing is waiting for your approval.")
                s.commit()
                return "Nothing is waiting for your approval."
            approval_id = pending.id
    out = decide(approval_id, decision, via=via)
    if not out["ok"] or decision != "approve":
        with get_session() as s:
            whatsapp.send_owner(s, out["message"])
            s.commit()
    return out["message"]


@app.post("/api/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    if config.VALIDATE_TWILIO_SIGNATURE:
        from twilio.request_validator import RequestValidator
        url = config.PUBLIC_BASE_URL.rstrip("/") + "/api/whatsapp/webhook"
        if not RequestValidator(config.TWILIO_AUTH_TOKEN).validate(url, dict(form), request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403, "Bad signature")
    sender = form.get("From", "")
    if config.OWNER_WHATSAPP and sender and sender != config.OWNER_WHATSAPP:
        return Response("<Response/>", media_type="application/xml")  # ignore strangers
    handle_owner_text(form.get("Body", ""), via="whatsapp")
    # Replies are sent by send_owner (REST API), so the webhook answers with an empty TwiML.
    return Response("<Response/>", media_type="application/xml")


@app.post("/api/whatsapp/simulate")
def whatsapp_simulate(payload: dict = Body(...)):
    """The phone panel on the website uses this - same code path as real WhatsApp."""
    return {"reply": handle_owner_text(payload.get("text", ""), via="whatsapp-simulator")}


@app.get("/api/messages")
def messages(audience: str = "owner", limit: int = 60):
    with get_session() as s:
        rows = s.exec(select(Message).where(Message.audience == audience)
                      .order_by(Message.id.desc()).limit(limit)).all()
        return [m.model_dump() for m in reversed(rows)]


@app.post("/api/brief")
def brief():
    with get_session() as s:
        body = orchestrator.send_brief(s)
        s.commit()
        return {"brief": body}


# ------------------------------------------------------------------ inputs
@app.post("/api/replies")
def add_reply(payload: dict = Body(...)):
    """Log a buyer's reply (email / WhatsApp text). The negotiator classifies it now."""
    with get_session() as s:
        inv = s.get(Invoice, payload.get("invoice_id", ""))
        if not inv:
            raise HTTPException(404, "Invoice not found")
        r = Reply(invoice_id=inv.id, buyer_id=inv.buyer_id, channel=payload.get("channel", "email"),
                  text=(payload.get("text") or "").strip())
        if not r.text:
            raise HTTPException(400, "Reply text is empty")
        s.add(r)
        s.flush()
        outcome = negotiator.process_reply(s, inv, r)
        s.commit()
        nxt = orchestrator.run_invoice(s, inv.id)
        s.commit()
        return {"classification": outcome, "next_action": nxt.get("action"), "next_outcome": nxt.get("outcome")}


@app.post("/api/invoices/{invoice_id}/payment")
def simulate_payment(invoice_id: str, payload: dict = Body(default={})):
    """Pretend the bank (Account Aggregator feed) reported a credit for this invoice."""
    with get_session() as s:
        inv = s.get(Invoice, invoice_id)
        if not inv:
            raise HTTPException(404, "Invoice not found")
        buyer = s.get(Buyer, inv.buyer_id)
        amount = float(payload.get("amount") or inv.outstanding)
        if inv.state == "FINANCED":   # buyer pays the TReDS financier, not us
            move(s, inv, "PAID", ledger.AGENT, "match_payment", detail="Buyer settled with TReDS financier",
                 evidence="TReDS settlement (mock)")
            inv.paid_amount, inv.paid_date = inv.amount, config.today()
            s.add(inv)
            msg = f"{buyer.name} settled #{inv.id} with the TReDS financier. Closed."
        else:
            s.add(BankTxn(txn_date=config.today(), amount=amount, live=True,
                          narration=f"NEFT CR {buyer.name.upper()} INV {inv.id}"))
            s.flush()
            paid = ledger.match_payments(s)
            msg = (f"{inr(amount)} received from {buyer.name} for #{inv.id}."
                   + (" Invoice closed." if inv.id in paid else " Part payment recorded."))
        whatsapp.send_owner(s, msg, invoice_id=inv.id)
        s.commit()
        return {"message": msg, "state": inv.state}


@app.post("/api/invoices/{invoice_id}/odr-filed")
def odr_filed(invoice_id: str):
    with get_session() as s:
        inv = s.get(Invoice, invoice_id)
        try:
            move(s, inv, "ODR_FILED", "Owner", "odr_filed", detail="Owner filed on the MSME ODR portal")
        except TransitionError as exc:
            raise HTTPException(409, str(exc))
        s.commit()
        return {"state": inv.state}


@app.get("/api/invoices/{invoice_id}/odr-pack", response_class=HTMLResponse)
def odr_pack(invoice_id: str):
    with get_session() as s:
        inv = s.get(Invoice, invoice_id)
        if not inv:
            raise HTTPException(404, "Invoice not found")
        return escalation.odr_pack_html(s, ledger.build(s, inv))


@app.get("/api/buyers")
def buyers():
    today = config.today()
    with get_session() as s:
        out = []
        for b in s.exec(select(Buyer)).all():
            invs = s.exec(select(Invoice).where(Invoice.buyer_id == b.id)).all()
            open_ = [i for i in invs if i.state not in ("PAID", "FINANCED", "ODR_FILED", "DRAFT", "AUDITED")]
            out.append({**b.model_dump(), "open_count": len(open_), "outstanding": sum(i.outstanding for i in open_),
                        "oldest_age": max([(today - i.invoice_date).days for i in open_], default=0)})
        out.sort(key=lambda r: -r["outstanding"])
        return out


@app.patch("/api/buyers/{buyer_id}")
def update_buyer(buyer_id: str, payload: dict = Body(...)):
    with get_session() as s:
        b = s.get(Buyer, buyer_id)
        if not b:
            raise HTTPException(404, "Buyer not found")
        for key in ("sensitive", "playbook", "ap_email", "ap_contact", "finance_head", "finance_email"):
            if key in payload:
                setattr(b, key, payload[key])
        s.add(b)
        s.commit()
        return b.model_dump()


@app.get("/api/forecast")
def forecast():
    with get_session() as s:
        fc = cash_optimiser.forecast(s)
        prop = cash_optimiser.financing_proposal(s)
        fin = None
        if prop and prop.get("invoice"):
            fin = {"invoice_id": prop["invoice"].id, "buyer": prop["buyer"].name, "choice": prop["choice"],
                   "costs": prop["costs"], "days_needed": prop["days_needed"], "pay_date": prop["pay_date"],
                   "explanation": prop["explanation"]}
        sup = s.get(Supplier, 1)
        return {"weeks": fc["weeks"], "daily": fc["daily"], "gap": fc["first_gap"], "events": fc["events"],
                "inflows": fc["inflows"][:25], "financing": fin,
                "assumptions": {"od_rate": config.OD_RATE_PCT, "treds_rate": config.TREDS_RATE_PCT,
                                "treds_fee": config.TREDS_FEE_PCT, "bank_rate": config.BANK_RATE_PCT,
                                "payroll": sup.payroll_amount, "monthly_bills": sup.monthly_bills,
                                "monthly_sales": sup.monthly_sales}}


@app.get("/api/activity")
def activity(limit: int = 60):
    with get_session() as s:
        rows = s.exec(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
        return [r.model_dump() for r in rows]


@app.get("/api/meta")
def meta():
    return {"transitions": TRANSITIONS, "autonomy": AUTONOMY_TABLE,
            "models": {"reason": config.MODEL_REASON, "cheap": config.MODEL_CHEAP,
                       "classify": config.MODEL_CLASSIFY, "vision": config.MODEL_VISION},
            "llm_mode": "online" if config.llm_online() else "offline"}


IMPORT_COLUMNS = ["invoice_no", "invoice_date", "buyer_name", "buyer_gstin", "buyer_ap_email", "amount",
                  "item", "po_number", "po_line", "qty", "udyam_printed", "sent_to"]


@app.get("/api/import/sample.csv", response_class=PlainTextResponse)
def sample_csv():
    t = config.today()
    rows = [
        ",".join(IMPORT_COLUMNS),
        f"5001,{t},Sahyadri Pumps Ltd,27AAACS4421K1ZP,ap@sahyadripumps.example,245000,CNC housing,PO-SP-5520,10,120,Y,ap@sahyadripumps.example",
        f"5002,{t},Nashik Valve Works,27AAFCN9087M1Z2,payables@nashikvalve.example,188500,Valve stem,PO-NV-310,,80,N,payables@nashikvalve.example",
        f"5003,{t - timedelta(days=12)},Sahyadri Pumps Ltd,27AAACS4421K1ZP,ap@sahyadripumps.example,96000,Flange 4in,PO-SP-5520,20,60,Y,purchase@sahyadripumps.example",
    ]
    return "\n".join(rows) + "\n"


@app.post("/api/import/invoices")
async def import_invoices(file: UploadFile = File(...)):
    """Input #1: an invoice export from Tally / Zoho / Busy as CSV (see sample.csv)."""
    text = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in ("invoice_no", "invoice_date", "buyer_name", "amount") if c not in (reader.fieldnames or [])]
    if missing:
        raise HTTPException(400, f"Missing columns: {', '.join(missing)}")
    created, skipped = [], []
    from app.db import PurchaseOrder
    with get_session() as s:
        for row in reader:
            inv_id = row["invoice_no"].strip()
            if not inv_id or s.get(Invoice, inv_id):
                skipped.append(inv_id)
                continue
            name = row["buyer_name"].strip()
            bid = "".join(ch for ch in name.lower() if ch.isalnum())[:24]
            b = s.get(Buyer, bid)
            if not b:
                ap = (row.get("buyer_ap_email") or "").strip() or f"ap@{bid}.example"
                b = Buyer(id=bid, name=name, gstin=(row.get("buyer_gstin") or "").strip(), persona="new buyer",
                          ap_contact="AP team", ap_email=ap, sales_email=f"purchase@{bid}.example",
                          finance_head="Finance head", finance_email=f"finance@{bid}.example", credit_days=30,
                          avg_days_to_pay=50, slip_days=7)
                s.add(b)
            inv_date = date.fromisoformat(row["invoice_date"].strip())
            po, line = (row.get("po_number") or "").strip() or None, (row.get("po_line") or "").strip()
            item, qty = (row.get("item") or "").strip(), int(float(row.get("qty") or 0))
            if po:
                # MVP: learn PO lines from the export (a real Tally sync would import POs separately)
                existing = s.exec(select(PurchaseOrder).where(PurchaseOrder.po_number == po)).all()
                if not any(p.item == item for p in existing):
                    used = {p.line_no for p in existing}
                    line_no = int(line) if line and int(line) not in used else (max(used, default=0) + 10)
                    s.add(PurchaseOrder(po_number=po, buyer_id=b.id, line_no=line_no, item=item, qty=max(qty, 1),
                                        rate=float(row["amount"]) / max(qty, 1)))
                    s.flush()
            inv = Invoice(id=inv_id, buyer_id=b.id, invoice_date=inv_date, amount=float(row["amount"]),
                          item=item, po_number=po, po_line=int(line) if line else None, qty=qty,
                          billing_gstin=(row.get("buyer_gstin") or b.gstin).strip(),
                          udyam_printed=(row.get("udyam_printed") or "Y").strip().upper().startswith("Y"),
                          sent_to=(row.get("sent_to") or "").strip(),
                          irn=f"IRN-{inv_id}", state="DRAFT" if inv_date >= config.today() else "SENT")
            s.add(inv)
            s.flush()
            log(s, inv.id, ledger.AGENT, "import", detail=f"Imported from CSV ({inv.state})", evidence=file.filename)
            created.append(inv_id)
        s.commit()
        results = []
        for inv_id in created:
            out = orchestrator.run_invoice(s, inv_id)
            s.commit()
            results.append({"invoice": inv_id, "action": out.get("action"), "outcome": out.get("outcome")})
    return {"created": created, "skipped": skipped, "agent_results": results}


@app.post("/api/reset")
def reset():
    """Rebuild the demo data (handy before a live demo)."""
    reset_db()
    from app.seed import seed
    seed()
    return {"ok": True}


app.include_router(mocks.router)

# The website (static files). Mounted last so /api and /mock win.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
