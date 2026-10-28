"""Collections Orchestrator ("Chief Receivables Agent") built with LangGraph.

Per invoice, every day:  observe -> plan -> specialist -> gate
  observe    : dossier, process new buyer replies, check the buyer's AP status,
               age-based state moves (code)
  plan       : the escalation ladder proposes allowed actions (code);
               Gemini picks the best one when there is a real choice
  specialist : the right agent drafts the message / computes the numbers
  gate       : 'auto' actions run now; others become an approval for the owner

Approvals are stored as rows, not as paused graphs, so a server restart never
loses one. Approving runs app.executor directly.
"""
import json
import logging
from datetime import date
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from sqlmodel import select

from app import config
from app import llm, whatsapp
from app.agents import auditor, buyer_intel, cash_optimiser, escalation, ledger, negotiator
from app.db import Approval, Invoice, Reply, get_session
from app.executor import execute
from app.state_machine import ACTION_LABELS, CLOSED_STATES, autonomy_for, can_move, log, move
from app.tools.finance import inr

AGENT = "Orchestrator"
logger = logging.getLogger("paymitra.orchestrator")


class RunState(TypedDict, total=False):
    invoice_id: str
    today: date
    dossier: dict
    candidates: list
    action: Optional[str]
    reason: str
    model: str
    draft: str
    payload: dict
    autonomy: str
    outcome: str
    approval_id: Optional[int]


class NextStep(BaseModel):
    action: str
    reason: str


def _session(config) -> Any:
    return config["configurable"]["session"]


# ---------------------------------------------------------------- observe
def observe(state: RunState, config) -> RunState:
    s = _session(config)
    today = state["today"]
    inv = s.get(Invoice, state["invoice_id"])
    d = ledger.build(s, inv, today)

    for r in s.exec(select(Reply).where(Reply.invoice_id == inv.id, Reply.processed == False)).all():  # noqa: E712
        negotiator.process_reply(s, inv, r, today)

    if inv.state not in ("DRAFT", "AUDITED") and inv.state not in CLOSED_STATES:
        rec = buyer_intel.check_ap(s, d)
        if inv.state == "SENT" and rec.status in ("LOGGED", "APPROVED") and d["age"] >= 1:
            execute(s, inv, "receipt_check", today=today)

    credit = min(d["buyer"].credit_days, 45)
    if inv.state == "ACKNOWLEDGED" and d["age"] >= credit and not inv.blocker:
        move(s, inv, "DUE", AGENT, "due", detail=f"Credit period of {credit} days ended")
    promised_future = any(date.fromisoformat(p["date"]) >= today for p in inv.get_promises())
    if (inv.state == "DUE" and "reminder" in inv.get_actions() and d["age"] >= credit + 10
            and not promised_future):
        move(s, inv, "SILENT", AGENT, "no_reply", detail="No commitment 10 days after due date")
    if inv.state == "PROMISED" and inv.get_promises() and not promised_future and d["age"] > credit:
        move(s, inv, "SILENT", AGENT, "promise_missed", detail="Promised date passed without payment")
        inv.promises = "[]"
    s.add(inv)
    return {"dossier": ledger.build(s, inv, today)}


# ---------------------------------------------------------------- plan
def ladder(d: dict, s) -> list[dict]:
    """The escalation ladder from the solution doc, as code."""
    inv, buyer, sup, age, today = d["invoice"], d["buyer"], d["supplier"], d["age"], d["today"]
    if inv.state in CLOSED_STATES:
        return []
    if inv.state == "DRAFT":
        return [{"action": "audit", "reason": "New invoice: audit before it leaves"}]
    done = set(inv.get_actions())
    c: list[dict] = []
    if inv.blocker and inv.state != "DISPUTED":
        return [{"action": "send_fix", "reason": f"Fix before you chase - {inv.blocker}"}]
    open_q = [r for r in d["replies"] if r.intent in ("query", "dispute") and r.processed]
    if inv.state == "DISPUTED" or (open_q and "answer_query" not in done):
        if "answer_query" not in done:
            c.append({"action": "answer_query", "reason": "Buyer raised a query/dispute - answer it first"})
        return c
    credit = min(buyer.credit_days, 45)
    promised_future = any(date.fromisoformat(p["date"]) >= today for p in inv.get_promises())
    if inv.state in ("SENT", "ACKNOWLEDGED") and age >= credit - 5 and "pre_due_nudge" not in done:
        c.append({"action": "pre_due_nudge", "reason": f"Due in {credit - age} days - friendly heads-up"})
    if promised_future:
        return c
    if 38 <= age < 46 and "note_43bh" not in done and negotiator.eligible_43bh(sup) and inv.state != "SENT":
        c.append({"action": "note_43bh",
                  "reason": f"Day {age}: a 43B(h) note to the finance head before day 45 protects their deduction"})
    if age >= credit + 3 and "reminder" not in done and inv.state in ("DUE", "SILENT"):
        c.append({"action": "reminder", "reason": f"{age - credit} days past due, no commitment yet"})
    if age >= credit + 7 and "voice_call" not in done and inv.state in ("DUE", "SILENT"):
        c.append({"action": "voice_call", "reason": "Email has not worked - a polite call to AP"})
    if age >= 46 and "formal_notice" not in done and inv.state in ("DUE", "SILENT", "PROMISED"):
        c.append({"action": "formal_notice", "reason": f"Day {age}: beyond the 45-day statutory limit"})
    if age >= 51 and "formal_notice" in done and "odr_pack" not in done:
        c.append({"action": "odr_pack", "reason": f"Day {age}: notice ignored - prepare the ODR filing pack"})
    return c


def plan(state: RunState, config) -> RunState:
    s = _session(config)
    d = state["dossier"]
    cands = ladder(d, s)
    if not cands:
        return {"candidates": [], "action": None}
    choice, reason, model = cands[0]["action"], cands[0]["reason"], "rules"
    if len(cands) > 1 and llm.config.llm_online():
        inv = d["invoice"]
        prompt = (
            "You are the receivables officer for an Indian MSME. Pick the single next best action for this "
            "invoice. Protect the buyer relationship; prefer fixing problems and the most effective lever.\n"
            f"Invoice #{inv.id}, buyer {d['buyer'].name} ({d['buyer'].persona}), amount {inv.outstanding}, "
            f"day {d['age']}, state {inv.state}. Buyer playbook: {d['buyer'].playbook or 'none'}.\n"
            f"Allowed actions (choose exactly one 'action' value): {json.dumps(cands)}"
        )
        step, model = llm.ask("reason", prompt, NextStep, fallback=lambda: NextStep(action=choice, reason=reason))
        if step.action in [c["action"] for c in cands]:   # the LLM may only pick an allowed move
            choice, reason = step.action, step.reason
        else:
            model = "rules"
    return {"candidates": cands, "action": choice, "reason": reason, "model": model}


# ---------------------------------------------------------------- specialist
def specialist(state: RunState, config) -> RunState:
    s = _session(config)
    d, action = state["dossier"], state["action"]
    inv = d["invoice"]
    payload: dict = {"model": state.get("model", "rules")}
    draft = ""
    if action == "audit":
        issues, model = auditor.audit(d)
        payload["model"] = model
        if issues:
            action = "fix_invoice"
            inv.blocker = "Readiness audit: " + "; ".join(i["message"] for i in issues)
            s.add(inv)
            log(s, inv.id, auditor.AGENT, "audit", detail=inv.blocker, model=model, state=inv.state)
            payload["issues"] = issues
            draft = auditor.fix_draft(d, issues, resubmit=False)
            return {"action": action, "draft": draft, "payload": payload,
                    "reason": "Readiness Auditor stopped this invoice before the buyer could reject it"}
        draft = f"Dear {d['buyer'].ap_contact},\n\nPlease find invoice #{inv.id} attached.\n\nRegards"
    elif action == "send_fix":
        issues, model = auditor.audit(d)
        payload.update(model=model, issues=issues)
        draft = auditor.fix_draft(d, issues, resubmit=True)
    elif action in ("pre_due_nudge", "reminder", "voice_call", "note_43bh", "answer_query"):
        draft, model = negotiator.draft(action, d)
        payload["model"] = model
    elif action == "formal_notice":
        draft = escalation.formal_notice(d)
        payload["interest"] = escalation.interest_statement(d)
    elif action == "odr_pack":
        st = escalation.interest_statement(d)
        payload["interest"] = st
        draft = (f"ODR filing pack for #{inv.id}: principal {inr(st['principal'])}, {st['days_late']} days late, "
                 f"Sec 16 interest {inr(st['interest'])}, total claim {inr(st['total'])}. "
                 f"Open the pack from the invoice page to review documents before filing.")
    return {"action": action, "draft": draft, "payload": payload}


# ---------------------------------------------------------------- gate
def gate(state: RunState, config) -> RunState:
    s = _session(config)
    d, action = state["dossier"], state["action"]
    inv, buyer = d["invoice"], d["buyer"]
    level = autonomy_for(action, buyer)
    if level == "auto":
        outcome = execute(s, inv, action, state.get("draft", ""), state.get("payload"), today=state["today"])
        return {"autonomy": level, "outcome": outcome}
    approval = create_approval(s, inv, action, state.get("reason", ""), state.get("draft", ""),
                               state.get("payload", {}), level)
    return {"autonomy": level, "approval_id": approval.id if approval else None,
            "outcome": "awaiting owner" if approval else "skipped (already pending or held)"}


def create_approval(s, inv: Invoice, action: str, reason: str, draft: str, payload: dict,
                    level: str) -> Approval | None:
    existing = s.exec(select(Approval).where(Approval.invoice_id == inv.id, Approval.action == action,
                                             Approval.status.in_(["PENDING", "HELD"]))).first()
    if existing:
        return None
    title = f"{ACTION_LABELS.get(action, action)} - #{inv.id}"
    a = Approval(invoice_id=inv.id, action=action, title=title, reason=reason, draft=draft,
                 payload=json.dumps(payload, default=str), autonomy=level)
    s.add(a)
    s.flush()
    log(s, inv.id, AGENT, "approval_requested", detail=f"{title}: {reason}", state=inv.state,
        model=payload.get("model", "rules"))
    return a


def _route(state: RunState) -> str:
    return "specialist" if state.get("action") else END


def build_graph():
    g = StateGraph(RunState)
    g.add_node("observe", observe)
    g.add_node("plan", plan)
    g.add_node("specialist", specialist)
    g.add_node("gate", gate)
    g.add_edge(START, "observe")
    g.add_edge("observe", "plan")
    g.add_conditional_edges("plan", _route, {"specialist": "specialist", END: END})
    g.add_edge("specialist", "gate")
    g.add_edge("gate", END)
    return g.compile()


GRAPH = build_graph()


def run_invoice(s, invoice_id: str, today: date | None = None) -> RunState:
    today = today or config.today()
    return GRAPH.invoke({"invoice_id": invoice_id, "today": today},
                        config={"configurable": {"session": s}})


# ---------------------------------------------------------------- cash
def propose_financing(s, today: date | None = None) -> Approval | None:
    p = cash_optimiser.financing_proposal(s, today)
    if not p or not p.get("invoice") or p["choice"] == "WAIT":
        return None
    inv = p["invoice"]
    action = "finance_treds" if p["choice"] == "TREDS" else "draw_od"
    payload = {"costs": p["costs"], "days_needed": p["days_needed"], "gap": p["gap"],
               "pay_date": p["pay_date"], "amount": inv.outstanding, "model": p["model"]}
    reason = p["explanation"]
    costs = " vs ".join(f"{k} {inr(v)}" for k, v in p["costs"].items())
    draft = (f"Cash gap {inr(p['gap']['shortfall'])} on {p['gap']['date']:%d %b} (payroll). "
             f"Options for #{inv.id} ({inr(inv.outstanding)}), {p['days_needed']} days: {costs}. "
             f"Recommend {p['choice']}.")
    return create_approval(s, inv, action, reason, draft, payload, autonomy_for(action, p["buyer"]))


# ---------------------------------------------------------------- daily cycle
def owner_line(a: Approval) -> str:
    return f"#{a.id} {a.title}\n{a.reason}\nReply 1 to approve, 2 to edit, 3 to hold."


def daily_cycle(today: date | None = None, notify: bool = True) -> dict:
    today = today or config.today()
    summary = {"processed": 0, "auto_actions": [], "new_approvals": [], "errors": []}
    with get_session() as s:
        ledger.match_payments(s, today)
        ids = [i.id for i in s.exec(select(Invoice).where(Invoice.state.not_in(list(CLOSED_STATES)))).all()]
        for inv_id in ids:
            try:
                out = run_invoice(s, inv_id, today)
                summary["processed"] += 1
                if out.get("autonomy") == "auto" and out.get("outcome"):
                    summary["auto_actions"].append(out["outcome"])
                if out.get("approval_id"):
                    summary["new_approvals"].append(out["approval_id"])
                s.commit()
            except Exception as exc:  # one bad invoice must not stop the cycle
                s.rollback()
                logger.exception("Invoice %s failed", inv_id)
                summary["errors"].append(f"{inv_id}: {exc}")
        fin = propose_financing(s, today)
        if fin:
            summary["new_approvals"].append(fin.id)
        s.commit()
        if notify:
            send_brief(s, today)
            s.commit()
    return summary


def send_brief(s, today: date | None = None) -> str:
    from app.api_views import kpis
    k = kpis(s, today)
    pending = s.exec(select(Approval).where(Approval.status == "PENDING").order_by(Approval.id)).all()
    lines = [f"Good morning {k['owner']}. {inr(k['outstanding'])} outstanding; {inr(k['due_this_week'])} "
             f"due this week."]
    if k["stuck_count"]:
        lines.append(f"{k['stuck_count']} invoices are stuck for fixable reasons ({inr(k['stuck_value'])}).")
    if k["gap"]:
        lines.append(f"Cash gap of {inr(k['gap']['shortfall'])} on {k['gap']['date']:%d %b} (payroll).")
    if pending:
        lines.append(f"\n{len(pending)} need your OK. First:")
        lines.append(owner_line(pending[0]))
        others = ", ".join(f"#{a.id} {a.title}" for a in pending[1:5])
        if others:
            lines.append(f"\nAlso waiting: {others}. Reply '1 <number>' to approve one of these.")
    else:
        lines.append("Nothing needs your approval today.")
    body = "\n".join(lines)
    whatsapp.send_owner(s, body, approval_id=pending[0].id if pending else None)
    return body
