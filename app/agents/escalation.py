"""Agent 6 - Escalation & Legal: Sec 15/16 notice and a filing-ready ODR pack.

Drafts only; the owner decides to send or file. Interest is computed by code
(tools.finance.sec16_interest); legal wording comes from vetted templates.
"""
import html
from datetime import date, timedelta

from sqlmodel import select

from app import config, mocks
from app.db import AuditLog, Invoice
from app.tools.finance import inr, sec16_interest

AGENT = "Escalation & Legal"


def interest_statement(dossier: dict) -> dict:
    inv, buyer = dossier["invoice"], dossier["buyer"]
    today = dossier["today"]
    appointed = inv.invoice_date + timedelta(days=min(buyer.credit_days, 45))
    days_late = max(0, (today - appointed).days)
    interest = sec16_interest(inv.outstanding, days_late)
    return {
        "principal": inv.outstanding, "invoice_date": inv.invoice_date, "appointed_day": appointed,
        "days_late": days_late, "bank_rate": config.BANK_RATE_PCT, "rate": 3 * config.BANK_RATE_PCT,
        "interest": interest, "total": round(inv.outstanding + interest, 2),
    }


def formal_notice(dossier: dict) -> str:
    inv, buyer, sup = dossier["invoice"], dossier["buyer"], dossier["supplier"]
    st = interest_statement(dossier)
    return (
        f"To: {buyer.finance_head}, {buyer.name} (GSTIN {buyer.gstin})\n"
        f"Subject: Payment of invoice #{inv.id} under Sections 15 and 16 of the MSMED Act, 2006\n\n"
        f"Dear {buyer.finance_head},\n\n"
        f"{sup.name}, a {sup.udyam_category.lower()} enterprise registered under Udyam no. {sup.udyam_no}, "
        f"supplied goods against PO {inv.po_number} and raised invoice #{inv.id} dated "
        f"{inv.invoice_date:%d %b %Y} for {inr(inv.amount)}. {inr(st['principal'])} remains unpaid beyond the "
        f"agreed period, which ended on {st['appointed_day']:%d %b %Y}.\n\n"
        f"Under Section 16, compound interest with monthly rests at three times the RBI bank rate "
        f"({st['rate']:.2f}% p.a.) accrues from that date. As on {dossier['today']:%d %b %Y} the interest is "
        f"{inr(st['interest'])}, and the total due is {inr(st['total'])}.\n\n"
        f"We value our relationship and request payment within 7 days. If it is not received, we will "
        f"approach the MSE Facilitation Council through the MSME ODR portal.\n\n"
        f"Regards,\n{sup.owner_name}\n{sup.name}\n\n"
        f"[Template text - have your CA review before sending]"
    )


def odr_pack_html(session, dossier: dict) -> str:
    inv, buyer, sup = dossier["invoice"], dossier["buyer"], dossier["supplier"]
    st = interest_statement(dossier)
    rows = session.exec(select(AuditLog).where(AuditLog.invoice_id == inv.id).order_by(AuditLog.at)).all()
    timeline = "".join(
        f"<tr><td>{r.at:%d %b %Y %H:%M}</td><td>{html.escape(r.agent)}</td>"
        f"<td>{html.escape(r.action)}</td><td>{html.escape(r.detail)}</td></tr>" for r in rows)
    checklist = "".join(f"<li>{html.escape(c)}</li>" for c in mocks.ODR_CHECKLIST)
    e = html.escape
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>ODR pack - invoice {e(inv.id)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:860px;margin:32px auto;padding:0 16px;color:#1d2433}}
h1{{font-size:22px}}h2{{font-size:16px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border:1px solid #ddd;padding:6px 8px;text-align:left}}
.note{{background:#fff7e6;padding:10px 12px;border-left:3px solid #d97706;font-size:13px}}</style></head><body>
<h1>MSME ODR filing pack - invoice #{e(inv.id)}</h1>
<p class="note">Prepared by PayMitra for owner review. Filing is the owner's decision; have your CA check the
interest method and documents before submitting on the MSME ODR portal.</p>
<h2>1. Parties</h2><table>
<tr><th>Supplier (claimant)</th><td>{e(sup.name)}<br>Udyam {e(sup.udyam_no)} - {e(sup.udyam_category)},
{e(sup.activity)}<br>GSTIN {e(sup.gstin)}</td></tr>
<tr><th>Buyer (respondent)</th><td>{e(buyer.name)}<br>GSTIN {e(buyer.gstin)}<br>Finance: {e(buyer.finance_head)}
({e(buyer.finance_email)})</td></tr></table>
<h2>2. Claim</h2><table>
<tr><th>Invoice</th><td>#{e(inv.id)} dated {inv.invoice_date:%d %b %Y}, PO {e(inv.po_number or '-')} line
{inv.po_line or '-'}, IRN {e(inv.irn or '-')}</td></tr>
<tr><th>Principal outstanding</th><td>{inr(st['principal'])}</td></tr>
<tr><th>Agreed period ended (appointed day)</th><td>{st['appointed_day']:%d %b %Y}</td></tr>
<tr><th>Days beyond appointed day</th><td>{st['days_late']}</td></tr>
<tr><th>Interest rate (3 x bank rate {st['bank_rate']:.2f}%)</th><td>{st['rate']:.2f}% p.a., monthly rests</td></tr>
<tr><th>Sec 16 interest as on {dossier['today']:%d %b %Y}</th><td><b>{inr(st['interest'])}</b></td></tr>
<tr><th>Total claim</th><td><b>{inr(st['total'])}</b></td></tr></table>
<h2>3. Document checklist</h2><ul>{checklist}</ul>
<h2>4. Follow-up history (from the audit log)</h2>
<table><tr><th>When</th><th>Agent</th><th>Action</th><th>Detail</th></tr>{timeline}</table>
</body></html>"""
