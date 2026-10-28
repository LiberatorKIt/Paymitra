"""Synthetic demo data (all illustrative): 1 supplier, 25 buyers, ~400 invoices, 18 months.

Includes the hero cases from the 5-minute demo script:
  #4471 Apex Auto     - day 38, on hold in the portal: PO line 10 vs PO line 20
  #4398 Sharma Fab.   - day 41, unpaid -> 43B(h) note to the finance head
  #4420 Kaveri Motors - Hinglish reply "50% next week, balance after QC"
  #4302 Northline     - chronic defaulter, notice ignored -> ODR pack
  #4475 Bharat Gears  - new invoice missing PO line + Udyam -> auditor stops it
  #4455, #4462        - two more stuck invoices (wrong GSTIN, sent to sales)
Run directly:  python -m app.seed
"""
import json
import random
from datetime import date, timedelta

from sqlmodel import select

from app import config
from app.db import (BankTxn, Buyer, Invoice, PurchaseOrder, Reply, Supplier, get_session, init_db)

RNG = random.Random(42)

PERSONAS = {
    "prompt payer":           {"avg": 38, "slip": 3},
    "monthly payment run":    {"avg": 58, "slip": 10},
    "disputes everything":    {"avg": 80, "slip": 20},
    "silent until escalated": {"avg": 105, "slip": 30},
    "partial payer":          {"avg": 62, "slip": 12},
}

OTHER_BUYERS = [
    ("deccan", "Deccan Tractors Ltd"), ("sahyadri", "Sahyadri Pumps Ltd"), ("indus", "Indus Valves Pvt Ltd"),
    ("narmada", "Narmada Castings Ltd"), ("konkan", "Konkan Auto Parts Pvt Ltd"),
    ("vidarbha", "Vidarbha Steel Works"), ("malwa", "Malwa Agro Equipments"),
    ("godavari", "Godavari Electricals Ltd"), ("tapi", "Tapi Forgings Pvt Ltd"), ("satpura", "Satpura Machines Ltd"),
    ("ganga", "Ganga Wheels Ltd"), ("aravalli", "Aravalli Bearings Pvt Ltd"), ("chambal", "Chambal Hydraulics"),
    ("mahanadi", "Mahanadi Motors Ltd"), ("krishna", "Krishna Compressors Ltd"), ("bhima", "Bhima Gearboxes Pvt Ltd"),
    ("pench", "Pench Springs Ltd"), ("sabarmati", "Sabarmati Tools Pvt Ltd"), ("yamuna", "Yamuna Fasteners Ltd"),
    ("cauvery", "Cauvery Couplings Ltd"),
]
PERSONA_CYCLE = ["prompt payer", "monthly payment run", "disputes everything", "partial payer",
                 "prompt payer", "monthly payment run", "silent until escalated", "prompt payer"]
ITEMS = ["Precision bush 32mm", "Hex bolt M12 (zinc)", "CNC shaft 40mm", "Machined flange 4in", "Gear blank 60T",
         "Bearing housing", "Valve stem SS304", "Pump impeller", "Bracket assembly", "Spacer ring 25mm"]


def _gstin(i: int) -> str:
    return f"27AA{chr(65 + i % 26)}C{1000 + i * 37:04d}{chr(65 + (i * 7) % 26)}1Z{i % 10}"


def _ladder_done(age: int, credit: int) -> list[str]:
    """Rungs that would already have happened before today."""
    rungs = [("receipt_check", 1), ("pre_due_nudge", credit - 5), ("note_43bh", 38), ("reminder", credit + 3),
             ("voice_call", credit + 7), ("formal_notice", 46), ("odr_pack", 51)]
    return [name for name, day in rungs if day < age]


def seed(today: date | None = None) -> None:
    global RNG
    RNG = random.Random(42)   # same demo data every time, including after "Reset demo data"
    today = today or config.today()
    init_db()
    with get_session() as s:
        if s.exec(select(Supplier)).first():
            return
        payroll_day = today + timedelta(days=9)  # = day 47 of invoice #4471
        sup = Supplier(name="Rajesh Precision Components Pvt Ltd", owner_name="Rajesh",
                       udyam_no="UDYAM-MH-26-0048213", udyam_category="Small", activity="Manufacturing",
                       gstin="27AAKCR4821M1Z6", payroll_amount=900000, payroll_next_date=payroll_day,
                       monthly_bills=6_600_000, monthly_sales=8_000_000, opening_cash=0)
        s.add(sup)

        run_day = (today + timedelta(days=14)).day
        buyers = [
            Buyer(id="apex", name="Apex Auto Components Ltd", gstin="27AABCA1234K1Z5", persona="monthly payment run",
                  ap_contact="Meena (AP)", ap_email="ap@apexauto.example", sales_email="purchase@apexauto.example",
                  finance_head="Mr. Kulkarni", finance_email="finance@apexauto.example", phone="+91 20 5555 0101",
                  on_treds=True, credit_days=45, payment_run_day=min(run_day, 28), avg_days_to_pay=58,
                  slip_days=21, has_portal=True,
                  playbook="Uploads only via the vendor portal. PO line and GRN number must match the PO."),
            Buyer(id="sharma", name="Sharma Fabricators Pvt Ltd", gstin="27AACCS7781L1Z2",
                  persona="silent until escalated", ap_contact="Ravi (AP)", ap_email="accounts@sharmafab.example",
                  sales_email="purchase@sharmafab.example", finance_head="Ms. Priya Iyer",
                  finance_email="priya.iyer@sharmafab.example", phone="+91 22 5555 0144", credit_days=30,
                  avg_days_to_pay=70, slip_days=14),
            Buyer(id="kaveri", name="Kaveri Motors Ltd", gstin="29AAECK5512P1Z9", persona="partial payer",
                  ap_contact="Suresh (AP)", ap_email="ap@kaverimotors.example", sales_email="buy@kaverimotors.example",
                  finance_head="Mr. Rao", finance_email="cfo@kaverimotors.example", credit_days=30,
                  avg_days_to_pay=62, slip_days=10),
            Buyer(id="northline", name="Northline Engineering Works", gstin="06AADCN3349Q1Z4",
                  persona="silent until escalated", ap_contact="Accounts desk", ap_email="accounts@northline.example",
                  sales_email="purchase@northline.example", finance_head="Mr. Bansal",
                  finance_email="finance@northline.example", credit_days=30, avg_days_to_pay=110, slip_days=30),
            Buyer(id="bharat", name="Bharat Gears Ltd", gstin="27AABCB6620D1Z8", persona="disputes everything",
                  ap_contact="Farah (AP)", ap_email="ap@bharatgears.example", sales_email="purchase@bharatgears.example",
                  finance_head="Mr. Desai", finance_email="finance@bharatgears.example", credit_days=30,
                  avg_days_to_pay=75, slip_days=15, has_portal=True),
        ]
        for i, (bid, name) in enumerate(OTHER_BUYERS):
            persona = PERSONA_CYCLE[i % len(PERSONA_CYCLE)]
            if bid == "konkan":
                persona = "silent until escalated"
            if bid == "godavari":
                persona = "disputes everything"
            p = PERSONAS[persona]
            buyers.append(Buyer(
                id=bid, name=name, gstin=_gstin(i + 3), persona=persona, ap_contact="AP team",
                ap_email=f"ap@{bid}.example", sales_email=f"purchase@{bid}.example",
                finance_head="Finance head", finance_email=f"finance@{bid}.example",
                credit_days=RNG.choice([30, 30, 45]),
                payment_run_day=RNG.randint(5, 25) if persona == "monthly payment run" else 0,
                avg_days_to_pay=p["avg"], slip_days=p["slip"], has_portal=RNG.random() < 0.3))
        for b in buyers:
            s.add(b)
        by_id = {b.id: b for b in buyers}

        hero_ids = {"4471", "4398", "4420", "4302", "4475", "4476", "4455", "4462"}
        weights = [0.6 if b.id in ("apex", "sharma", "kaveri", "northline", "bharat") else 1.0 for b in buyers]
        dates = sorted(today - timedelta(days=RNG.randint(2, 540)) for _ in range(392))
        next_id = 4001
        po_seq = 1000
        for inv_date in dates:
            while str(next_id) in hero_ids:
                next_id += 1
            inv_id = str(next_id)
            next_id += 1
            b = RNG.choices(buyers, weights)[0]
            credit = min(b.credit_days, 45)
            age = (today - inv_date).days
            # keep the demo deterministic: no random invoice lands exactly on an approval rung today
            while age in {credit + 7, 38, 46, 51}:
                inv_date -= timedelta(days=1)
                age += 1
            amount = round(RNG.uniform(100_000, 650_000), -2)
            item = RNG.choice(ITEMS)
            po_seq += 1
            po = f"PO-{b.id[:3].upper()}-{po_seq}"
            qty = RNG.randint(40, 600)
            s.add(PurchaseOrder(po_number=po, buyer_id=b.id, line_no=10, item=item, qty=qty, rate=amount / qty))
            inv = Invoice(id=inv_id, buyer_id=b.id, invoice_date=inv_date, amount=amount, item=item, po_number=po,
                          po_line=10, qty=qty, billing_gstin=b.gstin, udyam_printed=True, sent_to=b.ap_email,
                          irn=f"IRN{inv_id}{RNG.randint(1000, 9999)}", grn_no=f"GRN-{inv_id}")
            if RNG.random() < 0.08:  # historical invoices that were delayed by a fixable error
                inv.planted_error = RNG.choice(["po_line_mismatch", "wrong_gstin", "udyam_missing", "wrong_recipient"])

            persona = b.persona
            if persona == "prompt payer":
                pay_days = RNG.randint(28, 44)
            elif persona == "monthly payment run":
                pay_days = RNG.randint(45, 75)
            elif persona == "disputes everything":
                pay_days = RNG.randint(55, 115)
            elif persona == "silent until escalated":
                pay_days = RNG.randint(80, 150)
            else:
                pay_days = RNG.randint(45, 65)
            first_pay = inv_date + timedelta(days=pay_days)
            second_pay = first_pay + timedelta(days=RNG.randint(20, 45))

            if persona == "partial payer" and first_pay < today <= second_pay:
                inv.paid_amount = round(amount / 2, 2)
                s.add(BankTxn(txn_date=first_pay, amount=inv.paid_amount, matched_invoice=inv_id,
                              narration=f"NEFT CR {b.name.upper()} INV {inv_id} PART"))
                inv.promises = json.dumps([{"amount": round(amount - inv.paid_amount, 2),
                                            "date": second_pay.isoformat(), "note": "balance after QC"}])
                inv.state = "PROMISED" if age >= credit else "ACKNOWLEDGED"
            elif (second_pay if persona == "partial payer" else first_pay) < today:
                paid_on = second_pay if persona == "partial payer" else first_pay
                inv.state, inv.paid_amount, inv.paid_date = "PAID", amount, paid_on
                s.add(BankTxn(txn_date=paid_on, amount=amount, matched_invoice=inv_id,
                              narration=f"NEFT CR {b.name.upper()} INV {inv_id}"))
            else:
                if age <= 2:
                    inv.state = "SENT"
                elif age < credit:
                    inv.state = "ACKNOWLEDGED"
                elif persona == "silent until escalated" and age >= credit + 10:
                    inv.state = "SILENT"
                else:
                    inv.state = "DUE"
            if inv.state != "PAID":
                done = _ladder_done(age, credit)
                if inv.state == "SENT":
                    done = []
                inv.actions_done = json.dumps(done)
                if done:
                    inv.last_action = done[-1]
            s.add(inv)

        # ---------------- hero cases ----------------
        s.add(PurchaseOrder(po_number="PO-AX-7781", buyer_id="apex", line_no=10, item="Hex bolt M12 (zinc)",
                            qty=2000, rate=42))
        s.add(PurchaseOrder(po_number="PO-AX-7781", buyer_id="apex", line_no=20, item="Precision bush 32mm",
                            qty=1700, rate=400))
        s.add(PurchaseOrder(po_number="PO-SF-3390", buyer_id="sharma", line_no=10, item="Bracket assembly",
                            qty=650, rate=800))
        s.add(PurchaseOrder(po_number="PO-KM-1187", buyer_id="kaveri", line_no=10, item="Gear blank 60T",
                            qty=410, rate=1000))
        s.add(PurchaseOrder(po_number="PO-NL-0442", buyer_id="northline", line_no=10, item="CNC shaft 40mm",
                            qty=250, rate=1500))
        s.add(PurchaseOrder(po_number="PO-BG-2210", buyer_id="bharat", line_no=10, item="Spacer ring 25mm",
                            qty=1000, rate=110))
        s.add(PurchaseOrder(po_number="PO-BG-2210", buyer_id="bharat", line_no=20, item="Bearing housing",
                            qty=200, rate=1550))
        s.add(PurchaseOrder(po_number="PO-GD-5108", buyer_id="godavari", line_no=10, item="Machined flange 4in",
                            qty=260, rate=1000))
        s.add(PurchaseOrder(po_number="PO-KO-0921", buyer_id="konkan", line_no=10, item="Valve stem SS304",
                            qty=300, rate=600))
        s.add(PurchaseOrder(po_number="PO-SA-7310", buyer_id="sahyadri", line_no=10, item="Pump impeller",
                            qty=150, rate=1300))

        def hero(inv_id, buyer_id, days_ago, amount, state, item, po, line, qty, done, **kw):
            b = by_id[buyer_id]
            inv = Invoice(id=inv_id, buyer_id=buyer_id, invoice_date=today - timedelta(days=days_ago), amount=amount,
                          item=item, po_number=po, po_line=line, qty=qty, billing_gstin=b.gstin, udyam_printed=True,
                          sent_to=b.ap_email, irn=f"IRN{inv_id}7781", grn_no=f"GRN-{inv_id}", state=state,
                          actions_done=json.dumps(done), last_action=done[-1] if done else None)
            for k, v in kw.items():
                setattr(inv, k, v)
            s.add(inv)
            return inv

        hero("4471", "apex", 38, 680000, "ACKNOWLEDGED", "Precision bush 32mm", "PO-AX-7781", 10, 1700,
             ["receipt_check"], planted_error="po_line_mismatch")
        hero("4398", "sharma", 41, 520000, "DUE", "Bracket assembly", "PO-SF-3390", 10, 650,
             ["receipt_check", "pre_due_nudge", "reminder", "voice_call"])
        hero("4420", "kaveri", 44, 410000, "DUE", "Gear blank 60T", "PO-KM-1187", 10, 410,
             ["receipt_check", "pre_due_nudge", "note_43bh", "reminder", "voice_call"])
        hero("4302", "northline", 78, 375000, "ESCALATION_READY", "CNC shaft 40mm", "PO-NL-0442", 10, 250,
             ["receipt_check", "pre_due_nudge", "note_43bh", "reminder", "voice_call", "formal_notice"])
        hero("4455", "godavari", 33, 260000, "ACKNOWLEDGED", "Machined flange 4in", "PO-GD-5108", 10, 260,
             ["receipt_check"], billing_gstin="27AAGCG0000X1Z0", planted_error="wrong_gstin")
        hero("4462", "konkan", 24, 180000, "SENT", "Valve stem SS304", "PO-KO-0921", 10, 300, [],
             sent_to="purchase@konkan.example", planted_error="wrong_recipient")
        hero("4475", "bharat", 0, 310000, "DRAFT", "Bearing housing", "PO-BG-2210", None, 200, [],
             udyam_printed=False, sent_to="", irn=None, grn_no=None, planted_error="missing_po_line+udyam_missing")
        hero("4476", "sahyadri", 0, 195000, "DRAFT", "Pump impeller", "PO-SA-7310", 10, 150, [],
             sent_to="", irn="IRN44767310", grn_no=None)

        now = today
        s.add(Reply(invoice_id="4420", buyer_id="kaveri", channel="whatsapp", sender="Suresh (AP)",
                    text="Sir 50% next week release ho jayega, balance after QC clearance"))
        open_dues = [i for i in s.exec(select(Invoice).where(Invoice.state == "DUE")).all()
                     if i.id not in hero_ids]
        if len(open_dues) >= 2:
            s.add(Reply(invoice_id=open_dues[0].id, buyer_id=open_dues[0].buyer_id, channel="email",
                        text="Will check and revert."))
            s.add(Reply(invoice_id=open_dues[1].id, buyer_id=open_dues[1].buyer_id, channel="email",
                        text="Payment is scheduled in this Friday's run."))
        s.commit()

        _calibrate_cash(s, today, payroll_day)
        s.commit()


def _calibrate_cash(s, today: date, payroll_day: date) -> None:
    """Pick an opening balance so that this month's payroll leaves a gap of about Rs 4.2 L
    once the stuck invoices are counted as stuck (the situation in the solution doc)."""
    from app import mocks
    from app.agents import cash_optimiser, negotiator
    for inv in s.exec(select(Invoice).where(Invoice.state.not_in(["PAID", "DRAFT", "AUDITED"]))).all():
        mocks.ap_status(s, inv)   # what each buyer's AP system says today (deterministic)
    s.commit()

    # Look at the world as it will be after the first cycle (replies read, stuck invoices found),
    # inside a savepoint that is rolled back afterwards.
    nested = s.begin_nested()
    for r in s.exec(select(Reply).where(Reply.processed == False)).all():  # noqa: E712
        negotiator.process_reply(s, s.get(Invoice, r.invoice_id), r, today)
    for inv_id in ("4471", "4455", "4462"):
        s.get(Invoice, inv_id).blocker = "calibration"
    s.get(Supplier, 1).opening_cash = 0
    s.flush()
    fc = cash_optimiser.forecast(s, today)
    nested.rollback()

    week = next(w for w in fc["weeks"] if w["start"] <= payroll_day <= w["end"])
    opening = -week["closing"] - 420_000              # payroll week closes Rs 4.2 L short
    earlier = [w["closing"] for w in fc["weeks"] if w["end"] < week["start"]]
    if earlier and opening + min(earlier) < 50_000:   # never short before the payroll week
        opening = 50_000 - min(earlier)
    sup = s.get(Supplier, 1)
    sup.opening_cash = round(opening, -3)
    s.add(sup)


if __name__ == "__main__":
    from app.db import reset_db
    reset_db()
    seed()
    print("Seeded demo data.")
