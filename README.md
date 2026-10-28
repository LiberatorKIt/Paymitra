# PayMitra: the AI receivables officer for India's MSMEs

PayMitra is a team of AI agents that gets a small supplier paid within the legal 45 days. It audits each invoice before the buyer can reject it, finds out why a payment is stuck, chases the right person, and finances only what can't wait. The owner stays in control with one-tap WhatsApp approvals.

This repo is a working MVP: a Python backend with the agents, a website, a WhatsApp loop, sample data, tests and deploy files. Every outside system (Tally, GST IRN, vendor portals, TReDS, the bank feed, ODR) is a mock behind the same interface a real integration would use.

```
paymitra/
├── app/
│   ├── main.py            website + API + WhatsApp webhook (FastAPI)
│   ├── config.py          all settings, read from .env
│   ├── db.py              database tables (SQLite locally, Postgres online)
│   ├── llm.py             ONE wrapper for Gemini + Nemotron, with fallback
│   ├── state_machine.py   invoice states, allowed moves, who may approve what
│   ├── executor.py        the only place actions leave the system (guardrail)
│   ├── mocks.py           fake Tally / portal / IRN / Udyam / TReDS / bank feed / ODR
│   ├── whatsapp.py        Twilio sending + the website's phone simulator
│   ├── seed.py            demo data: 25 buyers, ~400 invoices, the hero cases
│   ├── tools/             maths only, never an LLM: interest, OD, TReDS, forecast
│   └── agents/            orchestrator (LangGraph) + the 6 specialist agents
├── web/                   the website (plain HTML/CSS/JS, no build step)
├── tests/                 pytest + the agent evaluation from the solution doc
├── data/eval_replies.csv  60 labelled buyer replies (English, Hindi, Hinglish)
├── Dockerfile, render.yaml, .env.example
```

## What goes in and what comes out

| Input | How it arrives |
| --- | --- |
| Invoices | CSV export from Tally / Zoho / Busy (Add data page), later a live sync |
| Buyer replies | Pasted or forwarded email / WhatsApp text (later: inbox integration) |
| Bank credits | "Record payment received" (later: Account Aggregator feed) |
| Owner decisions | WhatsApp replies 1 / 2 / 3, or buttons on the website |

| Output | Who gets it |
| --- | --- |
| Morning WhatsApp brief and approval requests | Owner |
| Corrected invoices, reminders, answers to queries | Buyer's AP team |
| 43B(h) note | Buyer's finance head |
| Wait vs overdraft vs TReDS recommendation | Owner |
| Sec 15/16 notice and ODR filing pack, with interest computed | Owner decides to send or file |
| Dashboard, cash forecast, full audit trail | Owner and accountant |

## 1. Run it on your laptop (15 minutes)

You need Python 3.11 or newer ([python.org](https://www.python.org/downloads/)). Open a terminal in this folder:

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# Mac / Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
uvicorn app.main:app --reload
```

Open http://localhost:8000. Demo data loads by itself on first run. With no API keys the agents use offline rules, so everything still works.

## 2. The 5-minute demo (matches the solution doc)

1. **Today page:** read the brief, then press **Run today's check**. The agents read replies, check buyer portals and line up actions. You'll see 3 invoices stuck for fixable reasons (₹11.2 L) and a ₹4.2 L payroll gap.
2. **The 45-day chart:** red dots are stuck invoices. Click #4471 (Apex Auto, day 38): it's on hold in their portal because the invoice says PO line 10 while the part is on PO line 20.
3. **WhatsApp panel (right):** reply `1`. The corrected invoice is sent and uploaded, and the bot asks about financing: TReDS ₹4,313 vs overdraft ₹6,781. Reply `1` again. #4471 is financed and the payroll gap is gone (see Cash forecast).
4. **Kaveri Motors #4420:** the Hinglish reply "Sir 50% next week release ho jayega, balance after QC clearance" was split into two dated promises.
5. **Bharat Gears #4475:** a new invoice the Readiness Auditor stopped (no PO line, Udyam number not printed). Approve "Fix and send".
6. **Northline #4302:** approve "Prepare ODR pack", then open the pack: Sec 16 interest computed, documents listed, full follow-up history.
7. **Sharma Fabricators #4398:** the 43B(h) note to Ms. Priya Iyer. Edit the draft, then approve.

Use **Add data → Reset demo data** before each rehearsal.

## 3. Turn on Gemini and Nemotron

1. Gemini key: [Google AI Studio](https://aistudio.google.com) → Get API key.
2. NVIDIA key: [build.nvidia.com](https://build.nvidia.com/models) → open a Nemotron model → Get API Key.
3. Put both in `.env` (`GEMINI_API_KEY=...`, `NVIDIA_API_KEY=...`) and restart. The sidebar then shows "AI Gemini + Nemotron".

Which model does what (all in `app/llm.py`; change model names in `.env`):

| Job | Model |
| --- | --- |
| Pick the next action when there's a real choice; spot subtle invoice issues | Gemini 3.8 Flash (`gemini-3.8-flash`) |
| Classify every buyer reply, extract % splits and timing | Nemotron 3.5 Lightning (`nvidia/nemotron-3.5-lightning-30b-a3b`) |
| Polish wording of reminders and briefs (numbers are checked to be unchanged) | Gemini 3.5 Flash-Lite |
| Read POD photos / portal screenshots (`llm.describe_image`) | Nemotron 3.5 Super VL |
| Interest, ageing, forecast, TReDS vs OD | Python only |

If one provider fails, `ask()` tries the other, then falls back to offline rules, so a live demo never stops. Every decision in the audit trail shows which model (or rule) made it.

Model names were checked on 28 Oct 2026. If a call fails with "model not found", look up the current name on the [Gemini models page](https://ai.google.dev/models) or the [NVIDIA catalogue](https://build.nvidia.com/models) and change it in `.env`.

## 4. Real WhatsApp with Twilio (optional)

The website has a WhatsApp simulator, and that's enough for most demos. To use a real phone:

1. Create a free [Twilio](https://www.twilio.com) account. Open Messaging → Try it out → WhatsApp sandbox, and send the join code from your phone.
2. In `.env`, set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `OWNER_WHATSAPP=whatsapp:+91<your number>`.
3. Give Twilio a public address for your server:
   - Locally: install [ngrok](https://ngrok.com), run `ngrok http 8000`, and copy the https URL.
   - Once deployed: use your Render URL.
4. In the sandbox settings, set "When a message comes in" to `https://<your-url>/api/whatsapp/webhook` (method POST).
5. Owner messages now arrive on the phone. Reply `1`, `2`, `3`, `1 7` (approve #7) or `brief`. Messages from any other number are ignored.

The sandbox shows plain text. Real tap buttons need a WhatsApp Business sender and Meta-approved templates (a pilot-stage task).

## 5. Put it on a real website (free tier, about 30 minutes)

**Non-technical step-by-step version: see `HANDOVER.md`.** Short version:

1. Push this folder to a GitHub repository (private is fine; `.env` is ignored, so keys stay private).
2. On [render.com](https://render.com): New → Blueprint → pick the repo. `render.yaml` creates the website **and** a free Postgres database, and wires them together (`DATABASE_URL`, `SECRET_KEY`, `CYCLE_TOKEN` are set automatically; the site's own address is picked up from `RENDER_EXTERNAL_URL`). Nothing to fill in.
3. Optional, under the web service's Environment tab: `GEMINI_API_KEY`, `NVIDIA_API_KEY` (AI on), `APP_PASSWORD` (login page), Twilio values (real WhatsApp).
4. Render's free Postgres expires after 30 days. Before then, upgrade it or point `DATABASE_URL` at a free [Neon](https://neon.tech) database. Demo data reseeds into an empty database automatically.
5. Optional, on [cron-job.org](https://cron-job.org): GET `/health` every 10 minutes (keeps the free site awake), and POST `/api/cycle` daily at 08:45 IST with the header `X-Cycle-Token: <CYCLE_TOKEN>`.

**Custom domain (optional).** In Render → Settings → Custom domains, add `app.yourdomain.in` and set the CNAME record your registrar shows.

Railway, Fly.io or any VPS also work: they all run the same `Dockerfile`.

## 6. Tests and the evaluation from the solution doc

```bash
pytest                          # maths vs hand-computed values + the full hero flow through the API
python -m tests.eval_agents     # reply intent (60), auditor recall (40+40), guardrails (20 red-team)
```

Offline result: 60/60 replies, 100% auditor recall with 0 false alarms, 0 actions without approval. The offline rules were written alongside this test set, so treat that score as optimistic. The number to put on the impact slide is the one you get with the API keys on.

## 7. From mock to real: what to swap

| Mock (file) | Real integration |
| --- | --- |
| CSV import (`main.py: import_invoices`) | Tally Prime XML/ODBC export or Zoho Books API |
| `mocks.ap_status` | Browser agent (Playwright) on the buyer's vendor portal, with the owner's login |
| `mocks.irn_lookup` | GST e-invoice IRN lookup through a GSP |
| `mocks.udyam_verify` | Udyam registration check |
| `mocks.aa_bank_feed` | Account Aggregator (FIU licence or partner) |
| `mocks.treds_quote` / `treds_finance` | RXIL / M1xchange / Invoicemart APIs |
| `whatsapp.send_buyer` (outbox) | Email (Gmail / Outlook API) and WhatsApp Business templates |

## Honest notes

- All demo data, prices and finance rates are illustrative. Have a CA confirm the Sec 16 method and the notice wording before real use.
- Live Gemini and Nemotron calls are wired but were not run in the build environment (no keys there). Run `python -m tests.eval_agents` with your keys to confirm.
- One supplier per deployment in this MVP. Multi-tenant (many MSMEs, CA logins) is the next step.
