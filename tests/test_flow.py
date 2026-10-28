"""End-to-end: the hero workflow from the demo script, through the real API."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.db import reset_db
    from app.main import app
    from app.seed import seed
    reset_db()
    seed()
    with TestClient(app) as c:
        yield c


def pending(client):
    return {a["invoice_id"] + ":" + a["action"]: a for a in client.get("/api/approvals").json()}


def test_daily_cycle_finds_stuck_invoices(client):
    out = client.post("/api/cycle").json()
    assert not out["errors"]
    p = pending(client)
    assert "4471:send_fix" in p            # portal hold diagnosed
    assert "4398:note_43bh" in p           # 43B(h) lever at day 41
    assert "4302:odr_pack" in p            # chronic defaulter
    assert "4475:fix_invoice" in p         # auditor stopped a new invoice
    assert "PO line" in p["4471:send_fix"]["reason"]
    s = client.get("/api/summary").json()
    assert s["stuck_count"] == 3 and round(s["stuck_value"]) == 1120000
    assert s["gap"] and 400000 < s["gap"]["shortfall"] < 440000


def test_hinglish_reply_split_into_two_promises(client):
    inv = client.get("/api/invoices/4420").json()
    assert inv["state"] == "PROMISED"
    assert len(inv["promises"]) == 2 and inv["promises"][0]["amount"] == 205000


def test_owner_approves_fix_on_whatsapp_then_treds(client):
    reply = client.post("/api/whatsapp/simulate", json={"text": "1"}).json()["reply"]
    assert "Sent and uploaded corrected #4471" in reply
    assert "TReDS" in reply or "TREDS" in reply
    inv = client.get("/api/invoices/4471").json()
    assert inv["invoice"]["po_line"] == 20 and inv["blocker"] is None
    fin = pending(client)["4471:finance_treds"]
    assert fin["payload"]["costs"]["TREDS"] < fin["payload"]["costs"]["OD"]
    # a bare "1" answers the question the bot just asked: finance #4471 on TReDS
    reply = client.post("/api/whatsapp/simulate", json={"text": "1"}).json()["reply"]
    assert "financed on TReDS" in reply
    assert client.get("/api/invoices/4471").json()["state"] == "FINANCED"
    assert client.get("/api/summary").json()["gap"] is None   # payroll is covered now


def test_bank_credit_closes_the_loop(client):
    out = client.post("/api/invoices/4471/payment", json={}).json()
    assert out["state"] == "PAID"


def test_edit_then_approve_43bh_note(client):
    a = pending(client)["4398:note_43bh"]
    assert "43B(h)" in a["draft"]
    client.post(f"/api/approvals/{a['id']}", json={"decision": "edit", "draft": a["draft"] + "\nThanks!"})
    out = client.post(f"/api/approvals/{a['id']}", json={"decision": "approve"}).json()
    assert out["ok"]
    msgs = client.get("/api/invoices/4398").json()["messages"]
    assert any("priya.iyer" in m["to"] and m["body"].endswith("Thanks!") for m in msgs)


def test_hold_is_respected(client):
    a = pending(client)["4455:send_fix"]
    client.post(f"/api/approvals/{a['id']}", json={"decision": "hold"})
    client.post("/api/cycle")
    assert "4455:send_fix" not in pending(client)      # not re-proposed after a hold


def test_odr_pack_has_interest(client):
    html = client.get("/api/invoices/4302/odr-pack").text
    assert "Sec 16 interest" in html and "MSME ODR filing pack" in html


def test_csv_import_runs_auditor(client):
    csv_text = client.get("/api/import/sample.csv").text
    out = client.post("/api/import/invoices", files={"file": ("tally.csv", csv_text, "text/csv")}).json()
    assert set(out["created"]) == {"5001", "5002", "5003"}
    actions = {r["invoice"]: r["action"] for r in out["agent_results"]}
    assert actions["5001"] == "audit"            # clean -> sent automatically
    assert actions["5002"] == "fix_invoice"      # no PO line + no Udyam -> stopped
    assert actions["5003"] == "send_fix"         # went to purchase@ instead of AP


def test_new_buyer_reply_dispute(client):
    out = client.post("/api/replies", json={"invoice_id": "4462",
                                             "text": "Rate difference on 40 pcs, please issue credit note"}).json()
    assert out["classification"]["intent"] == "dispute"


def test_guardrail_blocks_unapproved_action(client):
    from app.db import Invoice, get_session
    from app.executor import GuardrailError, execute
    with get_session() as s:
        inv = s.get(Invoice, "4302")
        with pytest.raises(GuardrailError):
            execute(s, inv, "formal_notice", "x")
