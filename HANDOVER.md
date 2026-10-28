# PayMitra — Handover Guide

28 Oct 2026

This guide puts PayMitra on the internet so anyone with the link can use it. **You do not need to install anything or type any commands**: everything happens in a web browser, by clicking. It takes about 30 minutes and costs nothing. Follow the parts in order and tick each step as you go.

## What PayMitra is

PayMitra is a website plus a team of AI helpers that gets small Indian manufacturers paid on time. Think of it as a digital accounts assistant. It checks each bill before it goes to a customer, finds out why a payment is stuck, reminds the right person politely, and suggests the cheapest way to cover a cash shortfall. The owner approves anything important with one tap on WhatsApp.

It is a working demo built for the Abhikalp 2026 hackathon. It comes with a made-up company (Rajesh Precision Components) and about 400 made-up invoices, so it can be shown straight away.

- **Ready now:** the website, the AI helpers, WhatsApp approvals (shown on the website), the demo data, and automatic checks.
- **Not yet:** connections to real accounting software, banks and buyer portals. These are simulated for now.

## Before you start

You need:

- [ ] A computer with **Google Chrome** or Microsoft Edge
- [ ] An **email address** you can open (for sign-up confirmations)
- [ ] The file **paymitra-handover.zip**
- [ ] About **30 minutes**
- [ ] *Optional, for the AI:* a Google account (for Gemini)

You will create two free accounts:

| Service | What it does for you | Cost |
| --- | --- | --- |
| [GitHub](https://github.com) | Stores the PayMitra files online | Free |
| [Render](https://render.com) | Runs the website and its database, and gives you a public link | Free |

First, unzip the file. On Windows, right-click it and choose **Extract All**; on a Mac, double-click it. You now have a folder called **paymitra**.

## Part 1: Put the files on GitHub (10 minutes)

GitHub is an online folder for code. Render (Part 2) reads the files from there.

- [ ] **1.** Go to [github.com](https://github.com) and click **Sign up**. Enter your email, a password and a username, then confirm the code GitHub emails you.
- [ ] **2.** Once signed in, click the **+** at the top right, then **New repository**.
- [ ] **3.** Under **Repository name**, type `paymitra`. Select **Private**. Leave everything else as it is and click **Create repository**.
- [ ] **4.** On the next page, find the line "…or **uploading an existing file**" and click that link.
- [ ] **5.** Open your **paymitra** folder on your computer. Select **everything inside it** (Ctrl+A on Windows, Cmd+A on a Mac) and drag it into the GitHub page.
- [ ] **6.** Wait until all the files appear in the list below the box. Then scroll down and click the green **Commit changes** button.
- [ ] **7.** Check: the repository page should now list `app`, `data`, `tests`, `web`, `Dockerfile`, `README.md` and `render.yaml`.

**The one mistake to avoid:** drag the files *inside* the folder, not the `paymitra` folder itself. If the repository shows only a single folder called `paymitra`, delete the repository (Settings → Delete this repository, at the bottom) and repeat steps 2–7.

It doesn't matter if `.gitignore` or `.env.example` don't upload. Macs hide files starting with a dot, and the website doesn't need them.

## Part 2: Launch the website on Render (10 minutes, plus waiting)

Render takes the files from GitHub and turns them into a live website with its own database. The setup file in the folder (`render.yaml`) tells Render exactly what to build, so you don't need to fill in any settings.

- [ ] **1.** Go to [render.com](https://render.com) and click **Get Started**. Choose **GitHub** to sign up, then click **Authorize** when GitHub asks.
- [ ] **2.** In the Render dashboard, click **+ New** (top right) and then **Blueprint**.
- [ ] **3.** If `paymitra` is not in the list, click **Configure account** (or **Connect GitHub**). On the GitHub page, allow Render access to the `paymitra` repository, save, and come back.
- [ ] **4.** Next to `paymitra`, click **Connect**.
- [ ] **5.** Type `paymitra` as the Blueprint name. Render shows that it will create two things, both on the **Free** plan:
  - **paymitra**, the website
  - **paymitra-db**, the database
- [ ] **6.** Click **Deploy Blueprint** (on some screens the button says **Apply**).
- [ ] **7.** Wait 5–10 minutes while Render builds everything. Click **paymitra** to watch the progress; text scrolling past is normal.
- [ ] **8.** When a green **Live** label appears, the website is ready. Its address is shown near the top of the page, something like `https://paymitra-ab12.onrender.com`. Copy it.

## Part 3: Check it works, then share the link (5 minutes)

- [ ] **1.** Open the website address in your browser. The first visit can take up to a minute, because the free plan wakes the site up.
- [ ] **2.** You'll see the **Today** page: "Good morning, Rajesh", a chart of red and blue dots, and a WhatsApp-style panel on the right. On a phone, the WhatsApp panel opens from the green button at the bottom.
- [ ] **3.** Click **Run today's check**. In a few seconds a morning message appears in the WhatsApp panel, and **Approvals** shows 6 items waiting.
- [ ] **4.** In the WhatsApp box, type `1` and press **Send**. The bot replies that the corrected invoice was sent, and offers TReDS financing.
- [ ] **5.** Type `1` and **Send** again. The bot confirms the money was financed. Open **Cash forecast**: it should say no week ends below zero.

If all five steps work, PayMitra is live.

**Share it.** Send the website address to anyone, by WhatsApp or email. It works on phones and computers, and nobody needs an account.

**Optional: add a password.** Do this if you only want invited people to get in.

1. In Render, open **paymitra** and click **Environment** on the left.
2. Click **Add Environment Variable**. For **Key** type `APP_PASSWORD`; for **Value** type the password you want.
3. Click **Save Changes**. If Render asks, choose to deploy.
4. After about 3 minutes, visitors will see a sign-in page. Share the password together with the link.

## Part 4: Switch on the AI (10 minutes)

Without this step PayMitra works on built-in rules, and the demo still runs. With it, Google's Gemini and NVIDIA's Nemotron do the thinking and the reading. You need two free "API keys", which are like passwords that let the website use these AI services.

**Get the Gemini key**

- [ ] **1.** Go to [aistudio.google.com](https://aistudio.google.com) and sign in with a Google account.
- [ ] **2.** Click **Get API key**, then **Create API key**. Copy the long code it shows.

**Get the NVIDIA key**

- [ ] **3.** Go to [build.nvidia.com](https://build.nvidia.com/models) and sign in (or create a free account).
- [ ] **4.** Search for **Nemotron**, open any Nemotron model, and click **Get API Key**. Generate it and copy it (it starts with `nvapi-`).

**Give both keys to the website**

- [ ] **5.** In Render, open **paymitra** and click **Environment**.
- [ ] **6.** Click **Add Environment Variable** twice and fill in:

| Key (type exactly) | Value |
| --- | --- |
| `GEMINI_API_KEY` | The Gemini key |
| `NVIDIA_API_KEY` | The NVIDIA key |

- [ ] **7.** Click **Save Changes** (choose to deploy if asked) and wait about 3 minutes.
- [ ] **8.** Check: at the bottom left of the website it now says **AI Gemini + Nemotron** instead of "offline rules".

Keep the keys private. Don't paste them into chats, emails or GitHub. If one ever leaks, delete it on the site where you made it and create a new one.

## Show it: the 5-minute demo

Before every demo, go to **Add data**, click **Reset demo data**, and click it again to confirm. Everything goes back to the start.

1. **Today page.** Read out the morning summary. Click **Run today's check**: PayMitra finds 3 invoices stuck for fixable reasons (₹11.2 L) and a ₹4.2 L shortfall on payroll day.
2. **The 45-day chart.** Each dot is an unpaid invoice; the red line is the 45-day legal limit. Click the red dot for Apex Auto **#4471**. It's on hold because the invoice says PO line 10, but the part is on PO line 20.
3. **WhatsApp panel.** Type `1`: the corrected invoice goes out, and PayMitra offers TReDS financing (₹4,313 vs ₹6,781 on the overdraft). Type `1` again: it's financed, and the payroll gap closes.
4. **Kaveri Motors #4420** (open it from **Invoices**). The Hinglish reply "50% next week, balance after QC" was split into two dated promises.
5. **Approvals → Bharat Gears #4475.** A new invoice was stopped before sending: no PO line, no Udyam number. Click **Fix and send**.
6. **Approvals → Sharma Fabricators #4398.** A polite 43B(h) tax-deduction note to the buyer's finance head. Edit a word in the draft, then send it.
7. **Approvals → Northline #4302.** Click **Prepare ODR pack**, open the invoice, and click **Open ODR pack**: a filing-ready legal pack with the interest worked out.

## If something goes wrong

| What you see | What to do |
| --- | --- |
| The site takes about a minute to open | Normal on the free plan: it sleeps after 15 quiet minutes. Wait, or see "Keeping it running" to keep it awake. |
| Render says the deploy **failed**, or it can't find `render.yaml` | Almost always the files went into a `paymitra` sub-folder on GitHub. Check that `Dockerfile` and `render.yaml` sit at the top of the repository; if not, redo Part 1. Then in Render, open **paymitra** → **Manual Deploy** → **Deploy latest commit**. |
| Bottom left still says **offline rules** | A key is missing or mistyped. Check the two key names in Render → Environment (capital letters, underscores, no spaces), save, and wait for the redeploy. |
| The AI is on but replies look like the rules | One AI service may be down or out of free quota. PayMitra switches to the other one, then to the rules, so the demo keeps working. Try again later. |
| Someone changed the demo data | **Add data** → **Reset demo data** (click twice). |
| Visitors are asked for a password you don't know | Look up or change `APP_PASSWORD` in Render → Environment. Delete it to remove the password. |
| The site stops working after about a month | The free database has expired. See "Keeping it running". |

## Keeping it running

**The free database lasts 30 days.** Render deletes a free database 30 days after it is created, with a 14-day grace period. Before that, do one of these:

- **Pay to keep it:** in Render, open **paymitra-db** and upgrade it to a paid plan.
- **Move to a free Neon database (about 10 minutes):**
  1. Sign up at [neon.tech](https://neon.tech) and create a project (pick Singapore if offered).
  2. Click **Connect** and copy the connection string. It starts with `postgresql://`.
  3. In Render, open **paymitra** → **Environment**, find `DATABASE_URL`, replace its value with the Neon string, and save.
  4. The demo data loads into Neon by itself.

**It sleeps when nobody visits.** The free website pauses after 15 quiet minutes, and the next visitor waits about a minute. To keep it awake before a demo or judging day:

1. Make a free account at [cron-job.org](https://cron-job.org).
2. Create a job with the URL `https://<your-address>/health`, running every 10 minutes.

**Optional: a daily automatic check.** Instead of pressing **Run today's check** yourself, add a second cron-job.org job:

- URL: `https://<your-address>/api/cycle`, method **POST**, every day at 8:45 am IST.
- Add a header named `X-Cycle-Token`. Its value is the `CYCLE_TOKEN` shown in Render → Environment.

**Changing anything later.** Upload the changed files to the GitHub repository (**Add file** → **Upload files**). Render notices and updates the website within a few minutes.

**Good to know.** Everyone who opens the link sees the same demo company, and anyone can press **Reset demo data**. That's fine for a demo. For real customers, each company would need its own login (see the next section).

Free-plan details were checked on 28 Oct 2026: [Render free plan](https://render.com/docs/free), [Render Blueprint reference](https://render.com/docs/yaml-spec), [Neon connection guide](https://neon.com/docs/get-started/connect-neon).

## For the developer taking over

This section is technical. Nobody needs it to run the website. `README.md` in the zip has more detail, and the `docs/` folder has the original solution document and slides.

**Where things stand**

| Part | Status |
| --- | --- |
| 6 agents + LangGraph orchestrator, invoice state machine, approvals, audit trail | Done |
| Maths (Sec 16 interest, forecast, TReDS vs OD) | Done, tested against hand calculations |
| Website, login, WhatsApp simulator, Twilio webhook | Done; Twilio not connected yet |
| Tests | 29 passing, on SQLite and Postgres |
| Gemini + Nemotron calls | Wired in, **not yet run with real keys** |
| Real Tally / GST / portal / bank / TReDS / ODR | Mocked in `app/mocks.py`, each behind a function a real integration can replace |
| Several companies on one site | Not built |

**Run it on a laptop** (Python 3.11 or newer). Open a terminal in the `paymitra` folder and run:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
uvicorn app.main:app --reload   # then open http://localhost:8000
pytest                          # 29 passed = nothing broken
python -m tests.eval_agents     # agent evaluation; run with keys for real numbers
```

**Where to change things**

| Change | File |
| --- | --- |
| Model names, finance rates | `.env`, or Render → Environment |
| Which model does which job, fallback order | `app/llm.py` → `_routes()` |
| Follow-up ladder timing (day 38, 46, 51…) | `app/agents/orchestrator.py` → `ladder()` |
| What needs approval | `app/state_machine.py` → `AUTONOMY` |
| Invoice checks | `app/agents/auditor.py` → `rule_check()` |
| Reading buyer replies | `app/agents/negotiator.py` → `CLASSIFY_PROMPT`, `rule_classify()` |
| Message and notice wording | `app/agents/negotiator.py` → `draft()`, `app/agents/escalation.py` |
| Money maths | `app/tools/` (update `tests/test_tools.py` too) |
| Demo data | `app/seed.py` |
| Swap a mock for a real system | `app/mocks.py` |
| Website pages / look | `web/app.js` / `web/styles.css` |

**Next tasks, in priority order**

- [ ] Run with real Gemini + NVIDIA keys and put the `tests.eval_agents` numbers on the impact slide. The offline 100% score is optimistic, because the rules were written alongside the test set.
- [ ] Make **Reset demo data** need a secret setting on the public site (`/api/reset` in `app/main.py`).
- [ ] Deploy, rehearse the demo, and record a backup video.
- [ ] Fix the solution doc: "Sharma Fabricators" appears as both buyer and supplier. In the app it is the buyer, and the supplier is Rajesh Precision Components.
- [ ] Have a CA check the Sec 16 interest method (3 × RBI bank rate, set to 5.75%) and the notice wording.
- [ ] Connect real WhatsApp through Twilio, then WhatsApp Business templates for a pilot.
- [ ] Several MSMEs per site: a company id on every table, plus owner / accountant / CA logins.
- [ ] Real integrations, one at a time: Tally/Zoho import, bank feed (Account Aggregator), TReDS.
- [ ] Buyer-portal browser agent (Playwright) and a Hindi voice bot, both mocked today.

**Accounts to hand over.** Keys are never in the zip, so each person creates their own Gemini and NVIDIA keys. For GitHub and Render, add the new person as a collaborator or workspace member, or they deploy their own copy with Parts 1–4.
