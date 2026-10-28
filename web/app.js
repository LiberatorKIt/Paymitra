/* PayMitra website - plain JavaScript, no build step. Talks only to /api. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const STATE = {
  DRAFT: "Draft", AUDITED: "Audited", SENT: "Sent", ACKNOWLEDGED: "Received by buyer", DUE: "Due",
  PROMISED: "Promised", DISPUTED: "Disputed", SILENT: "No reply", FIX_AND_RESUBMIT: "Being fixed",
  ESCALATION_READY: "Ready to escalate", FINANCED: "Financed", ODR_FILED: "ODR filed", PAID: "Paid",
};
const APPROVE_LABEL = {
  send_fix: "Send corrected invoice", fix_invoice: "Fix and send", note_43bh: "Send 43B(h) note",
  voice_call: "Place the call", answer_query: "Send reply", finance_treds: "Finance on TReDS",
  draw_od: "Draw overdraft", formal_notice: "Send notice", odr_pack: "Prepare ODR pack",
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function inr(v) {
  const n = Number(v || 0), a = Math.abs(n), sign = n < 0 ? "-" : "";
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)} L`;
  return `${sign}₹${Math.round(a).toLocaleString("en-IN")}`;
}
function dshort(iso) {
  if (!iso) return "-";
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return `${String(d).padStart(2, "0")} ${MONTHS[m - 1]}`;
}
function dtime(iso) {
  if (!iso) return "";
  const s = String(iso);
  return `${dshort(s)}, ${s.slice(11, 16)}`;
}
const PORTAL = { ON_HOLD: "On hold", NOT_RECEIVED: "Not received by AP", LOGGED: "Logged by AP",
  APPROVED: "Approved for payment", PAID: "Paid", NOT_SUBMITTED: "Not submitted yet" };
const stateTag = (s) => `<span class="state s-${esc(s)}">${esc(STATE[s] || s)}</span>`;

async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body ? "POST" : "GET"), headers: {} };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, init);
  if (r.status === 401) { location.href = "/login"; throw new Error("Login required"); }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) || `Request failed (${r.status})`);
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), Math.min(9000, 2500 + msg.length * 35));
}

async function busy(btn, fn) {
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner" aria-hidden="true"></span> ${label}`;
  try { return await fn(); }
  catch (e) { toast(e.message); }
  finally { btn.disabled = false; btn.innerHTML = label; }
}

/* ------------------------------------------------------------------ router */
const views = { today, invoices, invoice, approvals, cash, buyers, data: addData, how };
let current = "today";

async function route() {
  const [, name = "today", arg] = location.hash.replace(/^#\/?/, "/").split("/");
  current = views[name] ? name : "today";
  $$(".side nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === (current === "invoice" ? "invoices" : current)));
  const view = $("#view");
  if (!view.innerHTML) view.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    view.innerHTML = await views[current](decodeURIComponent(arg || ""));
    afterRender();
  } catch (e) {
    view.innerHTML = `<div class="panel empty"><h2>This page could not load</h2><p>${esc(e.message)}</p>
      <button class="btn" data-act="reload">Try again</button></div>`;
  }
  refreshChrome();
}
window.addEventListener("hashchange", () => { route(); $("#main").focus({ preventScroll: true }); window.scrollTo(0, 0); });

async function refreshChrome() {
  try {
    const k = await api("/api/summary");
    const c = $("#nav-approvals");
    c.textContent = k.pending_approvals;
    c.hidden = !k.pending_approvals;
    const ai = k.llm_mode === "online"
      ? `<b>AI</b> ${[k.gemini && "Gemini", k.nemotron && "Nemotron"].filter(Boolean).join(" + ")}`
      : `<b>AI</b> offline rules (add API keys)`;
    $("#mode-pill").innerHTML = `${ai}<br><b>WhatsApp</b> ${k.twilio ? "live via Twilio" : "simulator"}`;
    $("#logout").hidden = !k.auth;
  } catch (_) { /* chrome is best effort */ }
  loadChat();
}

/* ------------------------------------------------------------------ Today */
async function today() {
  const [k, ap, act, inv] = await Promise.all([
    api("/api/summary"), api("/api/approvals"), api("/api/activity?limit=12"), api("/api/invoices?open_only=true"),
  ]);
  const gap = k.gap;
  let brief = `Good morning, ${esc(k.owner)}. <strong>${inr(k.outstanding)}</strong> is owed to you across ${k.open_count} invoices, and ${inr(k.due_this_week)} falls due this week.`;
  if (k.stuck_count) brief += ` <strong>${k.stuck_count} invoices are stuck for fixable reasons</strong> (${inr(k.stuck_value)}).`;
  if (gap) brief += ` Payroll on ${dshort(gap.date)} leaves a gap of <strong>${inr(gap.shortfall)}</strong>.`;
  if (!k.cycle_run_today) brief += ` Run today's check to let the agents look at every invoice.`;
  return `
  <div class="page-head">
    <div><h1>Today</h1><p class="brief">${brief}</p></div>
    <button class="btn primary" data-act="cycle">Run today's check</button>
  </div>
  <section class="figures" aria-label="Key figures">
    <div class="fig"><div class="v">${inr(k.outstanding)}</div><div class="k">Owed to you</div></div>
    <div class="fig late"><div class="v">${inr(k.beyond_45)}</div><div class="k">Past 45 days (${k.beyond_45_pct}% of it)</div></div>
    <div class="fig late"><div class="v">${k.stuck_count ? inr(k.stuck_value) : "None"}</div><div class="k">Stuck, fixable (${k.stuck_count} invoices)</div></div>
    <div class="fig north"><div class="v">${k.collected_within_45_pct}%</div><div class="k">Paid within 45 days, last 6 months</div></div>
    <div class="fig ${gap ? "late" : ""}"><div class="v">${gap ? inr(gap.shortfall) : "Covered"}</div><div class="k">${gap ? `Cash gap on ${dshort(gap.date)}` : "Next 13 weeks of cash"}</div></div>
  </section>
  <section class="panel">${fortyFiveChart(inv)}</section>
  <div class="grid two" style="margin-top:20px">
    <section class="panel">
      <div class="panel-head"><h2>Needs your OK</h2><a href="#/approvals">All approvals</a></div>
      ${ap.length ? `<ul class="mini-list">${ap.slice(0, 6).map((a) => `
        <li><div><div class="t">${esc(a.label)}: #${esc(a.invoice_id)}</div>
          <div class="who">${esc(a.buyer)}, ${inr(a.amount)}</div></div>
          <div class="btn-row"><a class="btn" href="#/invoice/${esc(a.invoice_id)}">Review</a>
          <button class="btn primary" data-act="approve" data-id="${a.id}">${esc(APPROVE_LABEL[a.action] || "Approve")}</button></div></li>`).join("")}</ul>`
      : `<p class="empty">Nothing is waiting for you. ${k.cycle_run_today ? "" : "Run today's check to see what the agents suggest."}</p>`}
    </section>
    <section class="panel">
      <div class="panel-head"><h2>What the agents did</h2></div>
      ${activityList(act)}
    </section>
  </div>`;
}

function activityList(rows) {
  if (!rows.length) return `<p class="empty">No activity yet.</p>`;
  return `<ul class="log">${rows.map((r) => `
    <li><time>${dtime(r.at)}</time><div><span class="agent">${esc(r.agent)}</span>
      <a href="#/invoice/${esc(r.invoice_id)}">#${esc(r.invoice_id)}</a>
      ${r.to_state && r.from_state !== r.to_state ? stateTag(r.to_state) : ""}
      <div>${esc(r.detail || r.action)}</div>
      ${r.model && r.model !== "code" ? `<div class="model">Decided by: ${esc(r.model)}</div>` : ""}</div></li>`).join("")}</ul>`;
}

function hash01(s) {
  let h = 2166136261;
  for (const c of String(s)) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return ((h >>> 0) % 1000) / 1000;
}

function fortyFiveChart(rows) {
  const data = rows.filter((r) => !["DRAFT", "AUDITED"].includes(r.state));
  const W = 760, H = 250, L = 18, R = 18, T = 44, B = 40;
  const cap = 120, maxX = Math.min(cap, Math.max(90, ...data.map((r) => r.age)));
  const x = (age) => L + (Math.min(age, maxX) / maxX) * (W - L - R);
  const maxAmt = Math.max(...data.map((r) => r.outstanding), 1);
  const rad = (a) => 4 + 9 * Math.sqrt(a / maxAmt);
  const kind = (r) => (r.blocker ? "stuck" : r.state === "PROMISED" ? "promised" : "track");
  const fill = { stuck: "var(--late)", promised: "var(--good)", track: "var(--blue)" };
  const within = data.filter((r) => r.age <= 45), past = data.filter((r) => r.age > 45);
  const sum = (a) => a.reduce((s, r) => s + r.outstanding, 0);
  const ticks = [];
  for (let t = 0; t <= maxX; t += 15) ticks.push(t);
  // draw big dots first so small ones stay clickable on top
  const dots = [...data].sort((a, b) => b.outstanding - a.outstanding).map((r) => {
    const cy = T + 14 + hash01(r.id) * (H - T - B - 28);
    const tip = `<b>#${esc(r.id)} ${esc(r.buyer)}</b><br>${inr(r.outstanding)}, day ${r.age}<br>${esc(STATE[r.state] || r.state)}${r.blocker ? `<br>${esc(r.blocker)}` : ""}`;
    return `<circle class="dot" tabindex="0" role="link" aria-label="Invoice ${esc(r.id)}, ${esc(r.buyer)}, day ${r.age}"
      data-go="#/invoice/${esc(r.id)}" data-tip="${esc(tip)}" cx="${x(r.age).toFixed(1)}" cy="${cy.toFixed(1)}"
      r="${rad(r.outstanding).toFixed(1)}" fill="${fill[kind(r)]}" fill-opacity="${kind(r) === "track" ? 0.75 : 0.95}"/>`;
  }).join("");
  return `
  <div class="panel-head"><h2>Every open invoice against the 45-day line</h2>
    <span class="muted small">Dot size = amount. Click a dot to open it.</span></div>
  <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${within.length} invoices within 45 days, ${past.length} past 45 days">
    <rect x="${x(45)}" y="${T}" width="${x(maxX) - x(45)}" height="${H - T - B}" fill="var(--late-soft)" opacity=".7"/>
    <g class="grid">${ticks.map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${H - B}"/>`).join("")}</g>
    <g class="axis"><line x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/></g>
    ${ticks.map((t) => `<text x="${x(t)}" y="${H - B + 18}" text-anchor="middle">${t === maxX && maxX === cap ? `${t}+` : t}</text>`).join("")}
    <text x="${W - R}" y="${H - 4}" text-anchor="end">Days since invoice</text>
    <text x="${L}" y="${T - 22}" style="fill:var(--ink-2);font-size:13px">${within.length} within 45 days, ${inr(sum(within))}</text>
    <text x="${W - R}" y="${T - 22}" text-anchor="end" class="limit-label" style="font-size:13px">${past.length} past it, ${inr(sum(past))}</text>
    <line class="limit" x1="${x(45)}" x2="${x(45)}" y1="${T - 8}" y2="${H - B}"/>
    <text class="limit-label" x="${x(45) + 6}" y="${T + 4}">45-day legal limit</text>
    ${dots}
  </svg>
  <div class="legend">
    <span><i style="background:var(--blue)"></i>Moving normally</span>
    <span><i style="background:var(--late)"></i>Stuck for a fixable reason</span>
    <span><i style="background:var(--good)"></i>Buyer promised a date</span>
  </div>`;
}

/* ------------------------------------------------------------------ Invoices */
let invFilter = "open", invSearch = "";
const FILTERS = [
  ["open", "All open", (r) => !["PAID", "FINANCED", "ODR_FILED"].includes(r.state)],
  ["stuck", "Stuck", (r) => r.blocker && !["PAID", "FINANCED"].includes(r.state)],
  ["late", "Past 45 days", (r) => r.age > 45 && !["PAID", "FINANCED", "ODR_FILED"].includes(r.state)],
  ["promised", "Promised", (r) => r.state === "PROMISED"],
  ["silent", "No reply", (r) => r.state === "SILENT"],
  ["draft", "Drafts", (r) => r.state === "DRAFT"],
  ["closed", "Paid or financed", (r) => ["PAID", "FINANCED", "ODR_FILED"].includes(r.state)],
];
let invCache = [];

async function invoices() {
  invCache = await api("/api/invoices");
  return `
  <div class="page-head"><div><h1>Invoices</h1>
    <p class="lede">Every invoice and where it stands. Red means past the 45-day limit or stuck.</p></div></div>
  <div class="filters" role="group" aria-label="Filter invoices">
    ${FILTERS.map(([id, label]) => `<button class="chip ${invFilter === id ? "on" : ""}" data-act="filter" data-f="${id}" aria-pressed="${invFilter === id}">${label}</button>`).join("")}
    <label class="sr" for="inv-search">Search</label>
    <input class="search" id="inv-search" placeholder="Search invoice or buyer" value="${esc(invSearch)}">
  </div>
  <section class="panel"><div class="table-wrap" id="inv-table">${invoiceTable()}</div></section>`;
}

function invoiceTable() {
  const f = FILTERS.find((x) => x[0] === invFilter)[2];
  const q = invSearch.trim().toLowerCase();
  const rows = invCache.filter(f).filter((r) => !q || r.id.includes(q) || r.buyer.toLowerCase().includes(q));
  if (!rows.length) return `<p class="empty">No invoices match. Try another filter.</p>`;
  return `<table><thead><tr><th>Invoice</th><th>Buyer</th><th>Age</th><th class="num">Outstanding</th>
    <th>Status</th><th>What is happening</th><th>Expected</th></tr></thead><tbody>
    ${rows.slice(0, 300).map((r) => {
      const late = r.age > 45;
      const note = r.blocker ? `<span class="blocker">${esc(r.blocker)}</span>`
        : r.promises.length ? esc(r.promises.map((p) => `${inr(p.amount)} by ${dshort(p.date)}`).join(", "))
        : esc(r.last_action || "");
      return `<tr class="link" data-go="#/invoice/${esc(r.id)}" tabindex="0">
        <td><a href="#/invoice/${esc(r.id)}">#${esc(r.id)}</a></td><td>${esc(r.buyer)}</td>
        <td><div class="age"><span>${r.age}d</span><div class="agebar ${late ? "late" : ""}"><i style="width:${Math.min(100, (r.age / 90) * 100)}%"></i></div></div></td>
        <td class="num">${inr(r.outstanding)}</td><td>${stateTag(r.state)}</td><td>${note}</td>
        <td>${r.expected ? dshort(r.expected) : "-"}</td></tr>`;
    }).join("")}</tbody></table>
    ${rows.length > 300 ? `<p class="muted small">Showing 300 of ${rows.length}. Use search to narrow.</p>` : ""}`;
}

/* ------------------------------------------------------------------ Invoice detail */
const RAIL = ["DRAFT", "AUDITED", "SENT", "ACKNOWLEDGED", "DUE", "BRANCH", "END"];
function rail(state, blocked) {
  const pos = { DRAFT: 0, AUDITED: 1, SENT: 2, FIX_AND_RESUBMIT: 2, ACKNOWLEDGED: 3, DUE: 4, PROMISED: 5, DISPUTED: 5,
    SILENT: 5, ESCALATION_READY: 5, PAID: 6, FINANCED: 6, ODR_FILED: 6 }[state] ?? 0;
  const bad = blocked || ["DISPUTED", "SILENT", "ESCALATION_READY", "FIX_AND_RESUBMIT"].includes(state);
  const labels = ["Draft", "Audited", "Sent", "Received", "Due",
    pos === 5 ? STATE[state] : "Reply", pos === 6 ? STATE[state] : "Paid"];
  if (state === "FIX_AND_RESUBMIT") labels[2] = "Being fixed";
  return `<div class="rail" aria-label="Invoice journey: ${esc(STATE[state])}">${labels.map((l, i) =>
    `<div class="stop ${i < pos ? "done" : ""} ${i === pos ? "now" : ""} ${i === pos && bad ? "bad" : ""}">${esc(l)}</div>`).join("")}</div>`;
}

async function invoice(id) {
  const d = await api(`/api/invoices/${encodeURIComponent(id)}`);
  const inv = d.invoice, b = d.buyer_detail, st = d.interest;
  const pending = d.approvals.filter((a) => a.status === "PENDING");
  const late = d.age > 45;
  const canPack = ["ESCALATION_READY", "ODR_FILED"].includes(d.state) || d.approvals.some((a) => a.action === "odr_pack");
  return `
  <div class="page-head">
    <div><p class="muted small"><a href="#/invoices">Invoices</a></p>
      <h1>#${esc(d.id)} ${esc(d.buyer)}</h1>
      <p class="lede">${inr(d.outstanding)} outstanding of ${inr(d.amount)}. Raised ${dshort(d.invoice_date)}, day ${d.age}${late ? `, ${d.age - 45} days past the legal limit` : `, ${45 - d.age} days to the legal limit`}.</p></div>
    <div class="btn-row">
      <button class="btn" data-act="run-one" data-id="${esc(d.id)}">Run agents on this invoice</button>
      ${!["PAID"].includes(d.state) ? `<button class="btn" data-act="pay" data-id="${esc(d.id)}">Record payment received</button>` : ""}
      ${canPack ? `<a class="btn" href="/api/invoices/${esc(d.id)}/odr-pack" target="_blank" rel="noopener">Open ODR pack</a>` : ""}
      ${d.state === "ESCALATION_READY" ? `<button class="btn danger" data-act="filed" data-id="${esc(d.id)}">Mark ODR filed</button>` : ""}
    </div>
  </div>
  ${rail(d.state, !!d.blocker)}
  ${d.blocker ? `<div class="callout"><strong>Why it is stuck:</strong> ${esc(d.blocker)}</div>` : ""}
  ${d.state === "PAID" ? `<div class="callout ok"><strong>Paid</strong> on ${dshort(inv.paid_date)}.</div>` : ""}
  ${d.promises.length ? `<div class="callout ok"><strong>Buyer promised:</strong> ${esc(d.promises.map((p) => `${inr(p.amount)} by ${dshort(p.date)} (${p.note})`).join("; "))}</div>` : ""}
  ${pending.length ? `<section style="margin:18px 0"><h2>Waiting for your OK</h2>${pending.map(approvalCard).join("")}</section>` : ""}
  <div class="grid two" style="margin-top:18px">
    <div>
      <section class="panel"><h2>Dossier</h2>
        <dl class="facts">
          <dt>Status</dt><dd>${stateTag(d.state)}</dd>
          <dt>PO</dt><dd>${esc(inv.po_number || "Missing")} line ${esc(inv.po_line ?? "missing")}</dd>
          <dt>Item and quantity</dt><dd>${esc(inv.item)}, ${inv.qty} pcs</dd>
          <dt>GST e-invoice (IRN)</dt><dd>${esc(d.irn.status === "ACTIVE" ? d.irn.irn : "Not generated")}</dd>
          <dt>GRN</dt><dd>${esc(inv.grn_no || "Not yet")}</dd>
          <dt>Udyam printed</dt><dd>${inv.udyam_printed ? "Yes" : "<span class='blocker'>No</span>"}</dd>
          <dt>Billed to GSTIN</dt><dd>${esc(inv.billing_gstin)}${inv.billing_gstin !== b.gstin ? ` <span class="blocker">buyer's is ${esc(b.gstin)}</span>` : ""}</dd>
          <dt>Sent to</dt><dd>${esc(inv.sent_to || "Not sent")}</dd>
          <dt>Buyer portal</dt><dd>${esc(PORTAL[d.portal] || d.portal || "Not checked yet")}</dd>
          <dt>Expected payment</dt><dd>${d.expected ? dshort(d.expected) : "Not until it is fixed"}</dd>
          <dt>AP contact</dt><dd>${esc(b.ap_contact)}, ${esc(b.ap_email)}</dd>
          <dt>Finance head</dt><dd>${esc(b.finance_head)}, ${esc(b.finance_email)}</dd>
          <dt>Credit terms</dt><dd>${b.credit_days} days, ${esc(b.persona)}</dd>
        </dl>
      </section>
      ${d.po_lines.length ? `<section class="panel"><h2>Purchase order ${esc(inv.po_number)}</h2><table><thead><tr><th>Line</th><th>Item</th><th class="num">Qty</th></tr></thead>
        <tbody>${d.po_lines.map((p) => `<tr><td>${p.line_no}${p.line_no === inv.po_line ? " (on invoice)" : ""}</td><td>${esc(p.item)}</td><td class="num">${p.qty}</td></tr>`).join("")}</tbody></table></section>` : ""}
      ${st.days_late > 0 ? `<section class="panel"><h2>Interest the buyer owes (Sec 16)</h2>
        <dl class="facts"><dt>Agreed period ended</dt><dd>${dshort(st.appointed_day)}</dd>
        <dt>Days late</dt><dd>${st.days_late}</dd><dt>Rate</dt><dd>${st.rate.toFixed(2)}% a year, compounded monthly (3 × RBI bank rate)</dd>
        <dt>Interest so far</dt><dd><strong>${inr(st.interest)}</strong></dd></dl>
        <p class="muted small">Computed by code, not by the AI. Have your CA confirm before using it in a notice.</p></section>` : ""}
    </div>
    <div>
      <section class="panel"><h2>Log a reply from the buyer</h2>
        <form class="inline" data-form="reply" data-id="${esc(d.id)}">
          <label class="sr" for="reply-text">Buyer's reply</label>
          <textarea id="reply-text" rows="3" required placeholder="Paste the email or WhatsApp reply, e.g. 50% next week, balance after QC"></textarea>
          <div class="btn-row"><button class="btn primary" type="submit">Read the reply</button></div>
        </form>
        ${d.replies.length ? `<div style="margin-top:12px">${d.replies.slice().reverse().map((r) => `<div class="msg"><div class="meta">${dtime(r.received_at)}, ${esc(r.channel)}${r.intent ? `, read as <strong>${esc(r.intent)}</strong>` : ""}</div>${esc(r.text)}</div>`).join("")}</div>` : ""}
      </section>
      <section class="panel"><h2>Messages sent to the buyer</h2>
        ${d.messages.filter((m) => m.audience === "buyer").map((m) => `<div class="msg"><div class="meta">${dtime(m.at)}, ${esc(m.channel)} to ${esc(m.to)}<br><strong>${esc(m.subject)}</strong></div>${esc(m.body)}</div>`).join("") || `<p class="muted">None yet.</p>`}
      </section>
      <section class="panel"><h2>Audit trail</h2>${activityList(d.audit)}</section>
    </div>
  </div>`;
}

/* ------------------------------------------------------------------ Approvals */
let apprTab = "PENDING";
function approvalCard(a) {
  const p = a.payload || {};
  const done = a.status !== "PENDING";
  const costs = p.costs ? compareBars(p.costs) : "";
  const issues = p.issues && p.issues.length ? `<ul>${p.issues.map((i) => `<li>${esc(i.message)}: <strong>${esc(i.fix)}</strong></li>`).join("")}</ul>` : "";
  return `<article class="appr ${esc(a.autonomy)}" data-appr="${a.id}">
    <div class="appr-top"><div><h3>${esc(a.label)}: <a href="#/invoice/${esc(a.invoice_id)}">#${esc(a.invoice_id)}</a></h3>
      <div class="who">${esc(a.buyer || "")}${a.amount ? `, ${inr(a.amount)} outstanding` : ""}</div></div>
      <span class="tag ${esc(a.autonomy)}">${a.autonomy === "owner" ? "Only you can start this" : "Needs your OK"}</span></div>
    <p class="why">${esc(a.reason)}</p>
    ${issues}${costs}
    <label class="sr" for="draft-${a.id}">Draft</label>
    <textarea id="draft-${a.id}" ${done ? "readonly" : ""}>${esc(a.draft)}</textarea>
    ${done ? `<p class="muted small">${esc(a.status === "DONE" ? "Approved and done" : a.status.toLowerCase())}${a.decided_via ? ` via ${esc(a.decided_via)}` : ""} ${dtime(a.decided_at)}</p>` : `
    <div class="btn-row">
      <button class="btn primary" data-act="approve" data-id="${a.id}">${esc(APPROVE_LABEL[a.action] || "Approve")}</button>
      <button class="btn" data-act="save-edit" data-id="${a.id}">Save edit</button>
      <button class="btn" data-act="hold" data-id="${a.id}">Hold</button>
    </div>`}
  </article>`;
}

function compareBars(costs) {
  const entries = Object.entries(costs);
  const max = Math.max(...entries.map(([, v]) => v), 1);
  const best = entries.reduce((a, b) => (b[1] < a[1] ? b : a))[0];
  const name = { WAIT: "Wait", OD: "Overdraft", TREDS: "TReDS" };
  return `<div class="compare" aria-label="Cost of each option">${entries.map(([k, v]) => `
    <div class="row ${k === best ? "best" : ""}"><span>${name[k] || k}</span>
      <div class="bar" style="width:${Math.max(2, (v / max) * 100)}%"></div><span class="num">${inr(v)}</span></div>`).join("")}</div>`;
}

async function approvals() {
  const rows = await api(`/api/approvals?status=${apprTab === "PENDING" ? "PENDING" : "ALL"}`);
  return `
  <div class="page-head"><div><h1>Approvals</h1>
    <p class="lede">Anything a buyer could resent waits here. Edit the draft if you like, then approve. You can also reply 1, 2 or 3 on WhatsApp.</p></div></div>
  <div class="filters"><button class="chip ${apprTab === "PENDING" ? "on" : ""}" data-act="appr-tab" data-t="PENDING">Waiting</button>
    <button class="chip ${apprTab === "ALL" ? "on" : ""}" data-act="appr-tab" data-t="ALL">All decisions</button></div>
  ${rows.length ? rows.map(approvalCard).join("") : `<div class="panel empty">Nothing is waiting for you. The agents will add items after the next check.</div>`}`;
}

/* ------------------------------------------------------------------ Cash */
async function cash() {
  const f = await api("/api/forecast");
  const gap = f.gap, fin = f.financing, a = f.assumptions;
  return `
  <div class="page-head"><div><h1>Cash forecast</h1>
    <p class="lede">The next 13 weeks, from the dates each buyer is expected to pay. Stuck invoices count as nothing until they are fixed.</p></div></div>
  ${gap ? `<div class="callout"><strong>${gap.cause === "payroll" ? `Payroll on ${dshort(gap.date)}` : `Week of ${dshort(gap.week_start)}`} leaves you ${inr(gap.shortfall)} short.</strong>
    ${gap.recovers_on ? ` Cash recovers from the week of ${dshort(gap.recovers_on)}.` : ""}</div>`
    : `<div class="callout ok"><strong>No week ends below zero</strong> in the next 13 weeks.</div>`}
  <section class="panel">${cashChart(f.weeks, f.events)}</section>
  <div class="grid two" style="margin-top:20px">
    <section class="panel"><h2>Cheapest way to cover the gap</h2>
      ${fin ? `<p>${esc(fin.explanation)}</p>${compareBars(fin.costs)}
        <p class="muted small">For invoice <a href="#/invoice/${esc(fin.invoice_id)}">#${esc(fin.invoice_id)}</a> (${esc(fin.buyer)}), ${fin.days_needed} days until the buyer is expected to pay. The approval appears in Approvals after the next check.</p>`
        : `<p class="muted">${gap ? "No invoice can close this gap through TReDS yet: the buyers that are on TReDS have stuck or early invoices. Fixing stuck invoices is the cheapest move." : "Nothing to finance."}</p>`}
      <p class="muted small">Assumptions: overdraft ${a.od_rate}% a year, TReDS ${a.treds_rate}% plus ${a.treds_fee}% fee, payroll ${inr(a.payroll)} a month, bills ${inr(a.monthly_bills)} a month spread over working days, new sales collected from day 46 at ${inr(a.monthly_sales)} a month. All illustrative; change them in settings (.env).</p>
    </section>
    <section class="panel"><h2>Next expected receipts</h2>
      <table><thead><tr><th>Date</th><th>Invoice</th><th class="num">Amount</th><th>Based on</th></tr></thead><tbody>
      ${f.inflows.slice(0, 12).map((r) => `<tr><td>${dshort(r.date)}</td><td><a href="#/invoice/${esc(r.invoice_id)}">#${esc(r.invoice_id)}</a> ${esc(r.buyer)}</td><td class="num">${inr(r.amount)}</td><td class="muted small">${esc(r.basis)}</td></tr>`).join("")}
      </tbody></table></section>
  </div>`;
}

function cashChart(weeks, events) {
  const W = 760, H = 270, L = 64, R = 16, T = 28, B = 40;
  const vals = weeks.map((w) => w.closing);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const span = hi - lo || 1;
  const y = (v) => T + ((hi - v) / span) * (H - T - B);
  const bw = (W - L - R) / weeks.length;
  const step = niceStep(span / 4);
  const ticks = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);
  const payrollWeeks = new Set(events.map((e) => weeks.findIndex((w) => e.date >= w.start && e.date <= w.end)));
  const bars = weeks.map((w, i) => {
    const x0 = L + i * bw + 3, top = y(Math.max(0, w.closing)), h = Math.abs(y(w.closing) - y(0));
    const neg = w.closing < 0;
    const tip = `<b>Week of ${dshort(w.start)}</b><br>In ${inr(w.inflow)}<br>Out ${inr(w.outflow)}<br>Closing ${inr(w.closing)}`;
    return `<rect class="bar" data-tip="${esc(tip)}" tabindex="0" x="${x0.toFixed(1)}" y="${top.toFixed(1)}" width="${(bw - 6).toFixed(1)}"
      height="${Math.max(1, h).toFixed(1)}" rx="3" fill="${neg ? "var(--late)" : "var(--blue)"}" aria-label="Week of ${dshort(w.start)}, closing ${inr(w.closing)}"/>
      ${payrollWeeks.has(i) && !neg ? `<text x="${x0 + (bw - 6) / 2}" y="${(top - 6).toFixed(1)}" text-anchor="middle" style="fill:var(--ink-2)">Payroll</text>` : ""}
      ${neg ? `<text x="${x0 + (bw - 6) / 2}" y="${(y(0) - 10).toFixed(1)}" text-anchor="middle" style="fill:var(--late);font-weight:600">${inr(w.closing)}</text>
        <text x="${x0 + (bw - 6) / 2}" y="${(y(0) - 24).toFixed(1)}" text-anchor="middle" style="fill:var(--late)">${payrollWeeks.has(i) ? "Payroll" : "Short"}</text>` : ""}
      ${i % 2 === 0 && !neg ? `<text x="${x0 + (bw - 6) / 2}" y="${H - B + 18}" text-anchor="middle">${dshort(w.start)}</text>` : ""}`;
  }).join("");
  return `<div class="panel-head"><h2>Cash at the end of each week</h2></div>
  <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Weekly closing cash balance for 13 weeks">
    <g class="grid">${ticks.map((t) => `<line x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>`).join("")}</g>
    ${ticks.map((t) => `<text x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${inr(t)}</text>`).join("")}
    ${bars}
    <line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="var(--ink-2)" stroke-width="1.2"/>
  </svg>
  <details class="table-view"><summary>Show as a table</summary>
    <table><thead><tr><th>Week of</th><th class="num">Money in</th><th class="num">Money out</th><th class="num">Closing</th></tr></thead>
    <tbody>${weeks.map((w) => `<tr><td>${dshort(w.start)}</td><td class="num">${inr(w.inflow)}</td><td class="num">${inr(w.outflow)}</td><td class="num">${inr(w.closing)}</td></tr>`).join("")}</tbody></table>
  </details>`;
}
function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * p;
}

/* ------------------------------------------------------------------ Buyers */
async function buyers() {
  const rows = await api("/api/buyers");
  return `
  <div class="page-head"><div><h1>Buyers</h1>
    <p class="lede">How each customer pays, and what they need before they pay. Mark a buyer as sensitive and no message goes to them without your OK.</p></div></div>
  <section class="panel"><div class="table-wrap"><table><thead><tr><th>Buyer</th><th>How they pay</th><th class="num">Owed</th>
    <th class="num">Oldest</th><th>Terms</th><th>TReDS</th><th>Sensitive</th><th>What they need before paying</th></tr></thead><tbody>
    ${rows.map((b) => `<tr><td><strong>${esc(b.name)}</strong><div class="who">${esc(b.ap_email)}</div></td>
      <td>${esc(b.persona)}</td><td class="num">${inr(b.outstanding)}</td>
      <td class="num">${b.open_count ? `${b.oldest_age}d` : "-"}</td><td>${b.credit_days} days</td><td>${b.on_treds ? "Yes" : "No"}</td>
      <td><label class="toggle"><input type="checkbox" data-act="sensitive" data-id="${esc(b.id)}" ${b.sensitive ? "checked" : ""}> <span class="sr">Sensitive</span>${b.sensitive ? "Yes" : "No"}</label></td>
      <td class="small">${esc(b.playbook || "Nothing learned yet")}</td></tr>`).join("")}
  </tbody></table></div></section>`;
}

/* ------------------------------------------------------------------ Add data */
async function addData() {
  const open = await api("/api/invoices?open_only=true");
  return `
  <div class="page-head"><div><h1>Add data</h1>
    <p class="lede">PayMitra works from three inputs: your invoices, your buyers' replies and your bank credits.</p></div></div>
  <div class="grid two">
    <section class="panel"><h2>Import invoices from Tally, Zoho or Busy</h2>
      <p>Export your sales register as CSV with these columns:
        <code>invoice_no, invoice_date, buyer_name, buyer_gstin, buyer_ap_email, amount, item, po_number, po_line, qty, udyam_printed, sent_to</code>.
        New invoices dated today are audited before they go out.</p>
      <form data-form="import" class="inline">
        <div class="drop"><label for="csv">Choose a CSV file</label><br><input id="csv" type="file" accept=".csv,text/csv" required></div>
        <div class="btn-row"><button class="btn primary" type="submit">Import and audit</button>
          <a class="btn" href="/api/import/sample.csv" download="paymitra-sample.csv">Download a sample CSV</a></div>
      </form>
      <div id="import-result"></div>
    </section>
    <section class="panel"><h2>Log a buyer's reply</h2>
      <p class="muted">Paste any email or WhatsApp reply, in English, Hindi or Hinglish. The negotiator reads it and updates the invoice.</p>
      <form data-form="reply-any" class="inline">
        <label for="reply-inv">Invoice</label>
        <select id="reply-inv" class="field">${open.map((r) => `<option value="${esc(r.id)}">#${esc(r.id)} ${esc(r.buyer)}, ${inr(r.outstanding)}</option>`).join("")}</select>
        <label for="reply-any-text">Reply</label>
        <textarea id="reply-any-text" rows="3" required placeholder="Sir 50% next week, balance after QC"></textarea>
        <div class="btn-row"><button class="btn primary" type="submit">Read the reply</button></div>
      </form>
    </section>
  </div>
  <section class="panel"><h2>Demo controls</h2>
    <p class="muted">Bank credits arrive through "Record payment received" on an invoice (the Account Aggregator feed in a live setup).</p>
    <div class="btn-row">
      <button class="btn" data-act="brief">Send the WhatsApp brief now</button>
      <button class="btn danger" data-act="reset">Reset demo data</button>
    </div>
  </section>`;
}

/* ------------------------------------------------------------------ How it works */
async function how() {
  const m = await api("/api/meta");
  return `
  <div class="page-head"><div><h1>How it works</h1>
    <p class="lede">Each day an orchestrator looks at every open invoice, picks one next step from the moves the rules allow, and hands it to a specialist agent. Routine steps run on their own; anything a buyer could resent waits for you.</p></div></div>
  <div class="grid two">
    <section class="panel"><h2>Who does what</h2>
      <table><thead><tr><th>Agent</th><th>Job</th><th>Brain</th></tr></thead><tbody>
        <tr><td>Orchestrator</td><td>Picks the next best step per invoice</td><td>${esc(m.models.reason)} + rules</td></tr>
        <tr><td>Ledger and dossier</td><td>Joins invoice, PO, GRN, IRN, bank credits</td><td>Code; ${esc(m.models.vision)} for photos</td></tr>
        <tr><td>Readiness auditor</td><td>Finds errors before the buyer does</td><td>Rules + ${esc(m.models.reason)}</td></tr>
        <tr><td>Buyer intelligence</td><td>Portal status, expected pay date</td><td>Code</td></tr>
        <tr><td>Follow-up negotiator</td><td>Reads replies, drafts messages</td><td>${esc(m.models.classify)} reads, templates write</td></tr>
        <tr><td>Cash optimiser</td><td>13-week forecast, wait vs overdraft vs TReDS</td><td>Code; ${esc(m.models.cheap)} explains</td></tr>
        <tr><td>Escalation</td><td>Sec 16 interest, notice, ODR pack</td><td>Code + vetted templates</td></tr>
      </tbody></table>
      <p class="muted small">AI is ${m.llm_mode === "online" ? "on" : "off: running on offline rules. Add GEMINI_API_KEY and NVIDIA_API_KEY to turn it on"}. Every number is computed by code, never by a model.</p>
    </section>
    <section class="panel"><h2>What runs on its own</h2>
      <table><thead><tr><th>Step</th><th>Who decides</th></tr></thead><tbody>
      ${m.autonomy.map((a) => `<tr><td>${esc(a.label)}</td><td>${a.level === "auto" ? "Runs on its own" : a.level === "approve" ? "Your one-tap OK" : "Only you start it"}</td></tr>`).join("")}
      </tbody></table></section>
  </div>
  <section class="panel"><h2>Invoice states and allowed moves</h2>
    <table><thead><tr><th>From</th><th>Can move to</th></tr></thead><tbody>
    ${Object.entries(m.transitions).map(([k, v]) => `<tr><td>${stateTag(k)}</td><td>${v.map(stateTag).join(" ") || "<span class='muted'>Final</span>"}</td></tr>`).join("")}
    </tbody></table></section>`;
}

/* ------------------------------------------------------------------ events */
function afterRender() {
  const s = $("#inv-search");
  if (s) s.addEventListener("input", (e) => { invSearch = e.target.value; $("#inv-table").innerHTML = invoiceTable(); });
}

async function decide(id, decision, btn) {
  const ta = $(`#draft-${id}`);
  const body = { decision };
  if (ta && decision !== "hold") body.draft = ta.value;
  await busy(btn, async () => {
    const out = await api(`/api/approvals/${id}`, { body });
    toast(out.message);
    await route();
  });
}

document.addEventListener("click", async (e) => {
  const go = e.target.closest("[data-go]");
  if (go && !e.target.closest("a, button")) { location.hash = go.dataset.go; return; }
  const el = e.target.closest("[data-act]");
  if (!el) return;
  const act = el.dataset.act, id = el.dataset.id;
  if (act === "reload") return route();
  if (act === "cycle") return busy(el, async () => {
    const r = await api("/api/cycle", { method: "POST" });
    toast(`Checked ${r.processed} invoices. ${r.new_approvals.length} need your OK${r.auto_actions.length ? `, ${r.auto_actions.length} done automatically` : ""}.${r.errors.length ? ` ${r.errors.length} could not be checked.` : ""}`);
    await route();
  });
  if (act === "approve") return decide(id, "approve", el);
  if (act === "hold") return decide(id, "hold", el);
  if (act === "save-edit") return decide(id, "edit", el);
  if (act === "filter") { invFilter = el.dataset.f; return route(); }
  if (act === "appr-tab") { apprTab = el.dataset.t; return route(); }
  if (act === "run-one") return busy(el, async () => {
    const r = await api(`/api/invoices/${id}/run`, { method: "POST" });
    toast(r.action ? `${r.label}: ${r.outcome}. ${r.reason || ""}` : "Nothing to do on this invoice today.");
    await route();
  });
  if (act === "pay") return busy(el, async () => { toast((await api(`/api/invoices/${id}/payment`, { body: {} })).message); await route(); });
  if (act === "filed") return busy(el, async () => { await api(`/api/invoices/${id}/odr-filed`, { method: "POST" }); toast("Marked as filed on the ODR portal."); await route(); });
  if (act === "brief") return busy(el, async () => { await api("/api/brief", { method: "POST" }); toast("Brief sent to WhatsApp."); openPhone(); loadChat(); });
  if (act === "reset") {
    if (el.dataset.confirm !== "1") { el.dataset.confirm = "1"; el.textContent = "Click again to wipe and reload the demo"; return; }
    return busy(el, async () => { await api("/api/reset", { method: "POST" }); toast("Demo data reset."); location.hash = "#/today"; await route(); });
  }
});

document.addEventListener("change", async (e) => {
  const el = e.target;
  if (el.dataset && el.dataset.act === "sensitive") {
    try { await api(`/api/buyers/${el.dataset.id}`, { method: "PATCH", body: { sensitive: el.checked } }); toast(el.checked ? "Marked sensitive: every message to this buyer now needs your OK." : "Sensitive mark removed."); route(); }
    catch (err) { toast(err.message); }
  }
});

document.addEventListener("keydown", (e) => {
  const go = e.target.closest && e.target.closest("[data-go]");
  if (go && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); location.hash = go.dataset.go; }
});

document.addEventListener("submit", async (e) => {
  const f = e.target;
  const kind = f.dataset.form;
  if (!kind) return;
  e.preventDefault();
  const btn = f.querySelector("button[type=submit]");
  if (kind === "reply" || kind === "reply-any") {
    const invId = kind === "reply" ? f.dataset.id : $("#reply-inv").value;
    const text = f.querySelector("textarea").value;
    return busy(btn, async () => {
      const r = await api("/api/replies", { body: { invoice_id: invId, text } });
      const c = r.classification;
      let msg = `Read as ${c.intent} (${c.model}).`;
      if (c.promises) msg += " " + c.promises.map((p) => `${inr(p.amount)} by ${dshort(p.date)}`).join(", ") + ".";
      if (r.next_action) msg += ` Next step: ${r.next_action.replace(/_/g, " ")}.`;
      toast(msg);
      if (kind === "reply") await route(); else f.reset();
    });
  }
  if (kind === "import") {
    const fd = new FormData();
    fd.append("file", $("#csv").files[0]);
    return busy(btn, async () => {
      const r = await api("/api/import/invoices", { body: fd });
      $("#import-result").innerHTML = `<div class="callout ok"><strong>Imported ${r.created.length} invoices</strong>${r.skipped.length ? `, skipped ${r.skipped.length} already present` : ""}.
        <ul>${r.agent_results.map((x) => `<li><a href="#/invoice/${esc(x.invoice)}">#${esc(x.invoice)}</a>: ${esc((x.action || "no action").replace(/_/g, " "))}, ${esc(x.outcome || "")}</li>`).join("")}</ul></div>`;
      refreshChrome();
    });
  }
});

/* ------------------------------------------------------------------ tooltip */
const tip = $("#tip");
function showTip(target, x, y) {
  tip.innerHTML = target.dataset.tip;
  tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = `${Math.min(window.innerWidth - w - 8, x + 14)}px`;
  tip.style.top = `${Math.max(8, y - h - 12)}px`;
}
document.addEventListener("mousemove", (e) => {
  const t = e.target.closest && e.target.closest("[data-tip]");
  if (t) showTip(t, e.clientX, e.clientY); else tip.hidden = true;
});
document.addEventListener("focusin", (e) => {
  const t = e.target.closest && e.target.closest("[data-tip]");
  if (t) { const r = t.getBoundingClientRect(); showTip(t, r.right, r.top); } else tip.hidden = true;
});

/* ------------------------------------------------------------------ WhatsApp panel */
async function loadChat() {
  try {
    const msgs = await api("/api/messages?audience=owner&limit=40");
    const chat = $("#chat");
    chat.innerHTML = msgs.length ? msgs.map((m) => `<div class="bubble ${m.direction === "in" ? "me" : ""}">${esc(m.body)}<time>${dtime(m.at)}${m.delivered ? ' <span class="sent">sent to phone</span>' : ""}</time></div>`).join("")
      : `<p class="muted small" style="text-align:center">Run today's check or send "brief". Messages to the owner appear here${""}.</p>`;
    chat.scrollTop = chat.scrollHeight;
  } catch (_) { /* ignore */ }
}
async function say(text) {
  if (!text.trim()) return;
  try {
    await api("/api/whatsapp/simulate", { body: { text } });
    await loadChat();
    if (current !== "invoices") route(); else refreshChrome();
  } catch (e) { toast(e.message); }
}
$("#compose").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#say"); say(i.value); i.value = ""; });
$$(".quick button").forEach((b) => b.addEventListener("click", () => say(b.dataset.say)));
function openPhone() { $("#phone").classList.add("open"); }
$("#phone-open").addEventListener("click", () => { $("#phone").classList.toggle("open"); loadChat(); });
$("#phone-close").addEventListener("click", () => $("#phone").classList.remove("open"));
$("#logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }); location.href = "/login"; });

route();
setInterval(() => { if (!document.hidden) loadChat(); }, 15000);
