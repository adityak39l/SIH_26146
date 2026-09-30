"use strict";
const DATA = JSON.parse(document.getElementById("vigil-data").textContent);
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v == null ? "—" : v).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const num = (v, d = 0) => Number(v).toLocaleString("en-IN", {minimumFractionDigits: d, maximumFractionDigits: d});
const btc = (v) => num(v, 4) + " BTC";
const signed = (v, d = 2) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(d);
const iso = (ts) => new Date(ts * 1000).toISOString();
const when = (ts) => ts == null ? "—" : iso(ts).replace("T", " ").slice(0, 19) + " UTC";
const clock = (ts) => iso(ts).slice(11, 16);
const short = (s, n = 8) => s && s.length > 2 * n + 1 ? s.slice(0, n) + "…" + s.slice(-n) : s;
const GLYPH = {CRITICAL: "◆", HIGH: "▲", MEDIUM: "●", LOW: "○"};
const SEV_VAR = {CRITICAL: "var(--critical)", HIGH: "var(--serious)", MEDIUM: "var(--warning)", LOW: "var(--muted)"};
const sev = (level) => `<span class="sev ${esc(level)}"><i aria-hidden="true">${GLYPH[level] || "○"}</i>${esc(level)}</span>`;
const copyBtn = (text, label = "copy") => `<button class="copy" type="button" data-copy="${esc(text)}" aria-label="Copy ${esc(label)}">⧉</button>`;
const S = DATA.summary, CASES = DATA.cases;
const state = {selected: CASES.length ? CASES[0].case_id : null, q: "", sev: "ALL"};

/* ---------- tooltip, toast, copy (delegated) ---------- */
const tip = $("tip");
document.addEventListener("mousemove", (ev) => {
  const el = ev.target.closest && ev.target.closest("[data-tip]");
  if (!el) { tip.style.display = "none"; return; }
  tip.innerHTML = el.dataset.tip;
  tip.style.display = "block";
  const pad = 14, r = tip.getBoundingClientRect();
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - pad;
  tip.style.left = Math.max(8, x) + "px";
  tip.style.top = Math.max(8, y) + "px";
});
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 1400);
}
document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-copy]");
  if (!el) return;
  ev.stopPropagation();
  const text = el.dataset.copy;
  const done = () => toast("Copied");
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => toast("Copy failed"));
  else { const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); done(); }
});

/* ---------- theme ---------- */
(function theme() {
  const root = document.documentElement;
  let saved = new URLSearchParams(location.search).get("theme");
  try { saved = saved || localStorage.getItem("vigil-theme"); } catch (e) { /* storage unavailable */ }
  if (saved === "dark" || saved === "light") root.dataset.theme = saved;
  $("theme").addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("vigil-theme", root.dataset.theme); } catch (e) { /* storage unavailable */ }
  });
})();

/* ---------- shared chart pieces ---------- */
function hbar(label, value, max, right, tipHtml, overlay) {
  const w = max ? (value / max) * 100 : 0;
  const over = overlay ? `<div style="width:${max ? (overlay / max) * 100 : 0}%"></div>` : "";
  return `<div class="hbar" data-tip="${esc(tipHtml)}"><div>${esc(label)}</div>
    <div class="t"><div class="${overlay == null ? "" : "ctx"}" style="width:${w}%"></div>${over}</div><div class="n">${esc(right)}</div></div>`;
}
function ring(score, level) {
  const r = 38, c = 2 * Math.PI * r;
  return `<div class="ring" style="--c:${SEV_VAR[level]}"><svg width="88" height="88" viewBox="0 0 88 88" aria-hidden="true">
    <circle class="bg" cx="44" cy="44" r="${r}" stroke-width="8"></circle>
    <circle class="fg" cx="44" cy="44" r="${r}" stroke-width="8" stroke-dasharray="${(score / 100) * c} ${c}"></circle></svg>
    <div class="val"><div><b>${num(score, 1)}</b><span>risk / 100</span></div></div></div>`;
}
function factorRows(factors) {
  const shown = factors.filter((f) => Math.abs(f.shap_log_odds) >= 0.05);
  if (!shown.length) return `<div class="small">No signal moved this score by more than 0.05 log-odds.</div>`;
  const lo = Math.min(0, ...shown.map((f) => f.shap_log_odds)), hi = Math.max(0, ...shown.map((f) => f.shap_log_odds));
  const span = (hi - lo) || 1, zero = (-lo / span) * 100;
  return shown.map((f) => {
    const w = Math.abs(f.shap_log_odds) / span * 100, raise = f.shap_log_odds >= 0;
    const tipHtml = `<b>${esc(f.factor)}</b>Signal value ${esc(f.value)}<br>Contribution ${signed(f.shap_log_odds)} log-odds` +
      (raise && f.share_pct !== "" ? `<br>${esc(f.share_pct)}% of the upward push` : "");
    return `<div class="factor" data-tip="${esc(tipHtml)}"><div>${esc(f.factor)}</div>
      <div class="track"><div class="bar ${raise ? "raise" : "lower"}" style="left:${raise ? zero : zero - w}%;width:${Math.max(w, 0.6)}%"></div><div class="zero" style="left:${zero}%"></div></div>
      <div class="num">${signed(f.shap_log_odds)}</div></div>`;
  }).join("");
}

/* ---------- overview ---------- */
(function renderOverview() {
  const o = DATA.overview, by = S.cases_by_severity;
  const inflow = CASES.reduce((sum, c) => sum + c.inflow_btc, 0);
  const resolved = S.transactions ? Math.round(100 * S.origin_attributed / S.transactions) : 0;
  const headline = CASES.length
    ? `${num(S.cases)} suspected laundering operation${S.cases === 1 ? "" : "s"} found in ${num(S.transactions)} transactions`
    : `No suspicious operation found in ${num(S.transactions)} transactions`;
  const steps = [
    ["Captured", num(S.observations), "network announcements"],
    ["Joined", num(S.transactions), "transactions by TXID"],
    ["Attributed", resolved + "%", "origin IP resolved"],
    ["Clustered", num(S.entities), "wallet entities"],
    ["Flagged", num(S.flagged_transactions), "transactions at risk ≥ " + DATA.model_card.thresholds.medium],
    ["Cases", num(S.cases), num(by.CRITICAL) + " critical"],
  ];
  const maxT = Math.max(1, ...o.timeline.map((b) => b.total));
  const cols = o.timeline.map((b) => {
    const tipHtml = `<b>${clock(b.t)} – ${clock(b.t + o.bucket_s)} UTC</b>${b.total} transaction${b.total === 1 ? "" : "s"}<br>${b.flagged} flagged`;
    const rest = b.total - b.flagged;
    return `<div class="col" data-tip="${esc(tipHtml)}">` +
      (b.flagged ? `<div class="seg flag" style="height:${(b.flagged / maxT) * 100}%"></div>` : "") +
      (rest ? `<div class="seg rest" style="height:${(rest / maxT) * 100}%"></div>` : "") + `</div>`;
  }).join("");
  const last = o.timeline.length ? o.timeline[o.timeline.length - 1].t + o.bucket_s : 0;
  const maxN = Math.max(1, ...o.networks.map((n) => n.total));
  const nets = o.networks.map((n) => hbar(n.label, n.total, maxN, `${n.flagged} of ${n.total}`,
    `<b>${esc(n.label)}</b>${n.total} transactions announced first from this network type<br>${n.flagged} flagged (${n.total ? Math.round(100 * n.flagged / n.total) : 0}%)`, n.flagged)).join("");
  const maxC = Math.max(1, ...o.typologies.map((t) => t.cases));
  const typs = o.typologies.map((t) => hbar(t.typology, t.cases, maxC, `${t.cases} case${t.cases === 1 ? "" : "s"}`,
    `<b>${esc(t.typology)}</b>${t.cases} case${t.cases === 1 ? "" : "s"}, ${t.transactions} transactions<br>${esc(btc(t.inflow_btc))} entering those cases`)).join("");
  const top = CASES.slice(0, 6).map((c) => {
    const origin = c.origins.find((x) => x.resolved);
    return `<tr class="row-link" data-go="#cases/${esc(c.case_id)}" tabindex="0"><td>${sev(c.severity)}</td><td><b>${esc(c.case_id)}</b></td><td>${esc(c.typology)}</td>
      <td class="n">${esc(c.tx_count)}</td><td class="n">${esc(btc(c.inflow_btc))}</td><td>${origin ? esc(origin.category_label) + " · " + esc(origin.country) : "unresolved"}</td><td class="n"><b>${num(c.risk_score, 1)}</b></td></tr>`;
  }).join("");

  $("panel-overview").innerHTML = `
    <div class="card hero">
      <div>
        <div class="eyebrow">Capture summary</div>
        <h1>${esc(headline)}</h1>
        <p>${esc(btc(inflow))} moved through the flagged operations. Each case joins what the network saw (who announced it, from where) with what the ledger recorded (which wallets, how much), and explains its score signal by signal.</p>
        <div class="actions"><a class="btn primary" href="#cases">Review cases →</a><a class="btn" href="#evaluation">How accurate is it?</a><a class="btn" href="#method">How it works</a></div>
      </div>
      <div class="sev-tiles">
        ${["CRITICAL", "HIGH", "MEDIUM"].map((l) => `<button class="sev-tile" type="button" data-sev="${l}">${sev(l)}<b>${num(by[l])}</b><span class="small">case${by[l] === 1 ? "" : "s"}</span></button>`).join("")}
      </div>
    </div>
    <div class="funnel" aria-label="Pipeline stages">${steps.map(([k, v, h]) => `<div class="step"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="h">${esc(h)}</div></div>`).join("")}</div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><h2>Activity over the capture</h2><p class="desc">Transactions by first-seen time, in ${Math.round(o.bucket_s / 60)}-minute buckets.</p>
        <div class="legend"><span style="--c:var(--series-1)">flagged</span><span style="--c:var(--context)">not flagged</span></div>
        <div class="axis-y">${maxT} transactions</div><div class="cols">${cols}</div>
        <div class="axis-x"><span>${o.timeline.length ? clock(o.timeline[0].t) : ""}</span><span>${o.timeline.length ? iso(o.timeline[0].t).slice(0, 10) + " UTC" : ""}</span><span>${o.timeline.length ? clock(last) : ""}</span></div></div>
      <div class="card"><h2>Where flagged traffic was announced from</h2><p class="desc">Network type of the first-seen origin. The grey bar is every transaction from that network type; the blue part was flagged.</p>
        <div class="legend"><span style="--c:var(--series-1)">flagged</span><span style="--c:var(--context)">all transactions</span></div>${nets}</div>
    </div>
    <div class="grid g-side" style="margin-top:16px">
      <div class="card"><h2>Typologies found</h2><p class="desc">A case can show more than one pattern.</p>${typs || `<div class="small">None.</div>`}</div>
      <div class="card"><h2>Highest-risk cases</h2><p class="desc">Select a row to open the case.</p>
        <div class="scroll"><table><thead><tr><th>Severity</th><th>Case</th><th>Typology</th><th class="n">Tx</th><th class="n">Funds</th><th>Origin</th><th class="n">Risk</th></tr></thead><tbody>${top}</tbody></table></div></div>
    </div>`;
  $("panel-overview").querySelectorAll("[data-sev]").forEach((b) => b.addEventListener("click", () => { state.sev = b.dataset.sev; location.hash = "#cases"; renderCaseList(); }));
})();
document.addEventListener("click", (ev) => { const row = ev.target.closest("[data-go]"); if (row) location.hash = row.dataset.go; });
document.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && ev.target.dataset && ev.target.dataset.go) location.hash = ev.target.dataset.go; });

/* ---------- cases: list ---------- */
function caseMatches(c) {
  if (state.sev !== "ALL" && c.severity !== state.sev) return false;
  const q = state.q.trim().toLowerCase();
  if (!q) return true;
  const hay = [c.case_id, c.typology, ...c.origins.map((o) => o.ip + " " + o.asn + " " + o.category_label),
    ...c.transactions.map((t) => t.txid), ...c.terminal_outputs.map((t) => t.address)].join(" ").toLowerCase();
  return hay.includes(q);
}
function renderCaseList() {
  const counts = {ALL: CASES.length, CRITICAL: 0, HIGH: 0, MEDIUM: 0};
  CASES.forEach((c) => { counts[c.severity] = (counts[c.severity] || 0) + 1; });
  $("sev-filter").innerHTML = [["ALL", "All"], ["CRITICAL", "Critical"], ["HIGH", "High"], ["MEDIUM", "Medium"]]
    .map(([k, l]) => `<button class="chip" type="button" data-f="${k}" aria-pressed="${state.sev === k}">${l} ${counts[k]}</button>`).join("");
  $("sev-filter").querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => { state.sev = b.dataset.f; renderCaseList(); }));
  const shown = CASES.filter(caseMatches);
  $("case-list").innerHTML = shown.length ? shown.map((c) => `
    <button class="case-item" type="button" data-case="${esc(c.case_id)}" aria-current="${c.case_id === state.selected}">
      <div class="row"><span class="id">${esc(c.case_id)}</span><span class="score">${num(c.risk_score, 1)}</span></div>
      <div class="meter" style="--c:${SEV_VAR[c.severity]}"><div style="width:${c.risk_score}%"></div></div>
      <div class="row"><span>${sev(c.severity)}</span><span class="meta">${esc(btc(c.inflow_btc))}</span></div>
      <div class="meta">${esc(c.typology)} · ${esc(c.tx_count)} tx · ${esc(c.duration)}</div>
    </button>`).join("") : `<div class="empty">No case matches this filter.</div>`;
  $("case-list").querySelectorAll(".case-item").forEach((el) => el.addEventListener("click", () => { location.hash = "#cases/" + el.dataset.case; }));
}
$("q").addEventListener("input", (ev) => { state.q = ev.target.value; renderCaseList(); });
$("case-list").addEventListener("keydown", (ev) => {
  if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
  const items = [...$("case-list").querySelectorAll(".case-item")], i = items.indexOf(document.activeElement);
  const next = items[Math.min(items.length - 1, Math.max(0, i + (ev.key === "ArrowDown" ? 1 : -1)))];
  if (next) { ev.preventDefault(); next.focus(); location.hash = "#cases/" + next.dataset.case; }
});

/* ---------- cases: detail ---------- */
function flowSvg(c) {
  const txs = c.transactions, depth = txs.map(() => 0);
  c.edges.forEach(([a, b]) => { depth[b] = Math.max(depth[b], depth[a] + 1); });
  const rows = {}, pos = txs.map((_, i) => { const r = rows[depth[i]] = (rows[depth[i]] || 0) + 1; return [depth[i], r - 1]; });
  const NW = 96, NH = 42, GX = 38, GY = 14, PAD = 14;
  const x = (d) => PAD + d * (NW + GX), y = (r) => PAD + r * (NH + GY);
  const width = x(Math.max(...depth)) + NW + PAD, height = y(Math.max(...Object.values(rows)) - 1) + NH + PAD;
  const maxAmt = Math.max(...c.edges.map((e) => e[2]), 1e-8);
  const edges = c.edges.map(([a, b, amt]) => {
    const x1 = x(pos[a][0]) + NW, y1 = y(pos[a][1]) + NH / 2, x2 = x(pos[b][0]), y2 = y(pos[b][1]) + NH / 2, mx = (x1 + x2) / 2;
    return `<path class="edge" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" stroke-width="${(1.2 + 3 * Math.sqrt(amt / maxAmt)).toFixed(2)}" data-tip="${esc(`<b>${btc(amt)}</b>moved from ${short(txs[a].txid)} to ${short(txs[b].txid)}`)}"></path>`;
  }).join("");
  const nodes = txs.map((t, i) => {
    const tipHtml = `<b>${esc(short(t.txid, 10))}</b>${esc(when(t.timestamp))}<br>${esc(t.inputs)} in → ${esc(t.outputs)} out, ${esc(btc(t.value_btc))}` +
      `<br>Risk ${num(t.risk_score, 1)} (${esc(t.severity)})${t.bridge ? ", kept as a bridge" : ""}` +
      `<br>Origin ${esc(t.origin_ip)} (${esc(t.origin_country)}), confidence ${esc(t.origin_confidence)}`;
    return `<g class="node${t.bridge ? " bridge" : ""}" data-idx="${i}" transform="translate(${x(pos[i][0])},${y(pos[i][1])})" data-tip="${esc(tipHtml)}" tabindex="0" role="button" aria-label="Transaction ${esc(t.txid.slice(0, 10))}, risk ${num(t.risk_score, 1)}">
      <rect class="body" width="${NW}" height="${NH}" rx="7"></rect>
      <rect width="5" height="${NH - 12}" x="0" y="6" rx="2.5" fill="${SEV_VAR[t.severity]}"></rect>
      <text x="14" y="18">${GLYPH[t.severity]} ${num(t.risk_score, 1)}</text>
      <text class="id" x="14" y="32">${esc(t.txid.slice(0, 11))}</text></g>`;
  }).join("");
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Money flow between the transactions of ${esc(c.case_id)}">${edges}${nodes}</svg>`;
}
function txDetail(c, i) {
  const t = c.transactions[i];
  const factors = DATA.model_card.evidence.map((e, k) => ({factor: e.absent_label && t.evidence[k] < 0.5 ? e.absent_label : e.label,
    value: t.evidence[k], shap_log_odds: t.shap[k], share_pct: ""})).sort((a, b) => Math.abs(b.shap_log_odds) - Math.abs(a.shap_log_odds));
  return `<div class="row" style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center">
      <div><div class="eyebrow">Selected transaction</div><span class="mono hash">${esc(t.txid)}</span>${copyBtn(t.txid, "transaction ID")}</div>
      <div>${sev(t.severity)} &nbsp;<b>${num(t.risk_score, 1)}</b></div></div>
    <div class="kv">
      <div><span>First seen</span><b>${esc(when(t.timestamp))}</b></div>
      <div><span>Value</span><b>${esc(btc(t.value_btc))}</b></div>
      <div><span>Shape</span><b>${esc(t.inputs)} in → ${esc(t.outputs)} out</b></div>
      <div><span>First-seen origin</span><b class="mono">${esc(t.origin_ip)}</b></div>
      <div><span>Attribution confidence</span><b>${esc(t.origin_confidence)}${t.origin_confidence < 0.5 ? " · unresolved" : ""}</b></div>
      <div><span>Lead over next announcer</span><b>${t.origin_lead_ms == null ? "—" : esc(t.origin_lead_ms) + " ms"}</b></div>
      <div><span>GNN probability</span><b>${esc(t.gnn_prob)}</b></div>
      <div><span>Anomaly score</span><b>${esc(t.anomaly)}</b></div>
    </div><h3>Why this transaction</h3>${factorRows(factors)}`;
}
function renderCase() {
  const c = CASES.find((k) => k.case_id === state.selected);
  const box = $("case-detail");
  if (!c) { box.innerHTML = `<div class="empty">No transaction reached the reporting threshold in this capture.</div>`; return; }
  const total = c.factors.reduce((sum, f) => sum + f.shap_log_odds, 0), logit = c.base_value_log_odds + total;
  const origins = c.origins.map((o) => `<tr><td class="mono">${esc(o.ip)}${copyBtn(o.ip, "IP address")}</td><td><span class="tag">${esc(o.category_label)}</span></td><td>${esc(o.country)}</td>
    <td>${esc(o.asn)} · ${esc(o.asn_org)}</td><td class="n">${esc(o.transactions)}</td><td class="n">${o.resolved ? Number(o.mean_confidence).toFixed(2) : `<span class="small">unresolved · likely a relay</span>`}</td></tr>`).join("");
  const terminals = c.terminal_outputs.map((t) => `<tr><td class="mono hash">${esc(t.address)}${copyBtn(t.address, "address")}</td><td class="n">${esc(btc(t.amount_btc))}</td><td>${esc(t.status)}</td></tr>`).join("");
  const drivers = c.gnn_drivers.map((d) => `<span class="chip" data-tip="${esc(`<b>${d.label}</b>Neutralising this feature changes the GNN's log-odds by ${signed(-d.log_odds_drop)}`)}">${esc(d.label)}</span>`).join("");
  const entities = c.entities.length ? c.entities.map((e) => `<span class="tag">${esc(e.entity_id)} · ${esc(e.addresses)} addresses</span>`).join(" ") : `<span class="small">None: every input address in this case was spent on its own.</span>`;
  const txRows = c.transactions.map((t) => `<tr><td class="mono">${esc(clock(t.timestamp))}:${esc(iso(t.timestamp).slice(17, 19))}</td><td class="mono">${esc(short(t.txid, 8))}${copyBtn(t.txid, "transaction ID")}</td>
    <td>${esc(t.inputs)} → ${esc(t.outputs)}</td><td class="n">${esc(btc(t.value_btc))}</td><td class="mono">${esc(t.origin_ip)}</td><td class="n">${esc(t.origin_confidence)}</td><td>${sev(t.severity)}</td><td class="n"><b>${num(t.risk_score, 1)}</b></td></tr>`).join("");

  box.innerHTML = `<div class="stack">
    <div class="card">
      <div class="case-head">
        ${ring(c.risk_score, c.severity)}
        <div><div class="eyebrow">${esc(c.case_id)} &nbsp;${sev(c.severity)}</div><h2>${esc(c.typology)}</h2>
          <div class="chips" style="margin-top:8px">${c.typology_tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div></div>
        <div class="actions"><button class="btn" type="button" data-copy="${esc(location.href.split("#")[0] + "#cases/" + c.case_id)}">Copy link</button>
          <button class="btn" type="button" id="dl">JSON</button><button class="btn primary" type="button" id="pr">Print dossier</button></div>
      </div>
      <p class="summary">${esc(c.narrative)}</p>
      <div class="kv">
        <div><span>Funds entering the case</span><b>${esc(btc(c.inflow_btc))}</b></div>
        <div><span>Transactions</span><b>${esc(c.tx_count)}</b></div>
        <div><span>First seen</span><b>${esc(when(c.first_seen))}</b></div>
        <div><span>Duration</span><b>${esc(c.duration)}</b></div>
        <div><span>Mean risk</span><b>${num(c.mean_risk, 1)}</b></div>
        <div><span>Outputs leaving the case</span><b>${esc(c.terminal_output_count)}</b></div>
      </div>
    </div>
    <div class="card">
      <h2>Why this case was flagged</h2>
      <p class="desc">Exact Shapley contribution of each evidence signal to the risk score, averaged over the flagged transactions. Red bars push the score up, blue bars pull it down.</p>
      <div class="legend"><span style="--c:var(--raise)">raises risk (+)</span><span style="--c:var(--lower)">lowers risk (−)</span></div>
      ${factorRows(c.factors)}
      <div class="equation"><span>Base value <b>${signed(c.base_value_log_odds)}</b></span><span>+ contributions <b>${signed(total)}</b></span><span>= log-odds <b>${signed(logit)}</b></span>
        <span>→ risk <b>${num(100 / (1 + Math.exp(-logit)), 1)}</b> for the average flagged transaction</span></div>
      <h3>What the graph neural network reacted to</h3><div class="chips">${drivers}</div>
    </div>
    <div class="card">
      <h2>Money flow</h2>
      <p class="desc">One box per transaction, left to right in spending order. The number is its risk score; line thickness follows the amount moved. Select a box to see that transaction's own explanation.</p>
      <div class="legend">${["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((l) => `<span style="--c:${SEV_VAR[l]}">${GLYPH[l]} ${l.toLowerCase()}</span>`).join("")}</div>
      <div class="flow" id="flow">${flowSvg(c)}</div><div id="tx-detail"></div>
    </div>
    <div class="card">
      <h2>Network-layer attribution</h2>
      <p class="desc">IP addresses that announced these transactions first. Confidence is the calibrated probability that the first announcer is the true origin. A Tor exit identifies the relay, not the sender.</p>
      <div class="scroll"><table><thead><tr><th>First-seen IP</th><th>Network</th><th>Country</th><th>ASN</th><th class="n">Tx</th><th class="n">Confidence</th></tr></thead><tbody>${origins}</tbody></table></div>
      <h3>Where the funds went</h3>
      <div class="scroll"><table><thead><tr><th>Address</th><th class="n">Amount</th><th>Status</th></tr></thead><tbody>${terminals}</tbody></table></div>
      <h3>Entities</h3><div class="chips">${entities}</div>
    </div>
    <div class="card"><details><summary>All ${esc(c.tx_count)} transactions in this case</summary>
      <div class="scroll"><table><thead><tr><th>Time (UTC)</th><th>TXID</th><th>In → out</th><th class="n">Value</th><th>First-seen IP</th><th class="n">Conf.</th><th>Severity</th><th class="n">Risk</th></tr></thead><tbody>${txRows}</tbody></table></div></details></div>
    <div class="card"><h2>Integrity</h2>
      <p class="desc">SHA-256 over this dossier record. Any later edit changes the hash.</p>
      <div class="mono hash">${esc(c.evidence_hash)}${copyBtn(c.evidence_hash, "dossier hash")}</div>
      <p class="small" style="margin:12px 0 0">${esc(c.notes)}</p></div>
  </div>`;
  box.querySelectorAll(".node").forEach((node) => {
    const pick = () => {
      box.querySelectorAll(".node").forEach((n) => n.classList.toggle("selected", n === node));
      $("tx-detail").innerHTML = txDetail(c, Number(node.dataset.idx));
    };
    node.addEventListener("click", pick);
    node.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(); } });
  });
  $("pr").addEventListener("click", () => { box.querySelectorAll("details").forEach((d) => { d.open = true; }); window.print(); });
  $("dl").addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(c, null, 2)], {type: "application/json"}));
    a.download = c.case_id + ".json";
    a.click();
    URL.revokeObjectURL(a.href);
  });
}

/* ---------- origins ---------- */
(function renderOrigins() {
  const rows = DATA.origins.map((o) => `<tr><td class="mono">${esc(o.ip)}${copyBtn(o.ip, "IP address")}</td><td><span class="tag">${esc(o.category_label)}</span></td><td>${esc(o.country)}</td><td>${esc(o.asn)} · ${esc(o.asn_org)}</td>
    <td class="n">${esc(o.transactions)}</td><td class="n">${o.flagged ? `<b>${esc(o.flagged)}</b>` : "0"}</td><td class="n">${num(o.max_risk, 1)}</td><td class="n">${Number(o.mean_confidence).toFixed(2)}</td></tr>`).join("");
  $("panel-origins").innerHTML = `<div class="card"><h2>First-seen origins</h2>
    <p class="desc">Every IP that announced at least one transaction before any other peer, ranked by flagged transactions. Country, ASN and network type come from the offline table (${esc(DATA.meta.geo_source)}); nothing is looked up online. ${num(S.origin_unresolved)} transactions had no reliable origin and are not attributed to anyone.</p>
    <div class="scroll"><table><thead><tr><th>IP</th><th>Network</th><th>Country</th><th>ASN</th><th class="n">Transactions</th><th class="n">Flagged</th><th class="n">Peak risk</th><th class="n">Mean confidence</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
})();

/* ---------- evaluation ---------- */
(function renderEvaluation() {
  const e = DATA.evaluation, m = DATA.meta.model, card = DATA.model_card;
  const bar = (v, c) => `<div class="databar"><div class="t"><div style="width:${(v * 100).toFixed(1)}%;--c:${c}"></div></div><span>${v.toFixed(3)}</span></div>`;
  let html = "";
  if (e) {
    const d = e.detectors, fused = d.fused, base = d.rule_baseline;
    const high = e.origin.by_confidence.find((b) => b.bucket.startsWith("0.75")) || {};
    const whole = e.scenarios.filter((s) => s.coverage === 1).length;
    html += `<div class="grid g3">
      <div class="stat"><div class="k">F1 of the fused risk score</div><div class="v">${fused.f1.toFixed(3)}</div><div class="h"><span class="up">▲ ${(fused.f1 / base.f1).toFixed(1)}×</span> the single-transaction rule (${base.f1.toFixed(3)})</div></div>
      <div class="stat"><div class="k">Laundering transactions caught</div><div class="v">${fused.tp} of ${fused.tp + fused.fn}</div><div class="h">recall ${fused.recall.toFixed(3)}, with ${fused.fp} false alarms (precision ${fused.precision.toFixed(3)})</div></div>
      <div class="stat"><div class="k">Origin attribution, confident cases</div><div class="v">${high.accuracy == null ? "—" : (high.accuracy * 100).toFixed(1) + "%"}</div><div class="h">${esc(high.correct)} of ${esc(high.total)} correct at confidence ≥ 0.75</div></div>
      <div class="stat"><div class="k">Operations recovered whole</div><div class="v">${whole} of ${e.scenarios.length}</div><div class="h">every transaction of the operation in one case</div></div>
    </div>`;
    const rows = Object.entries(d).map(([key, x]) => `<tr class="${key === "fused" ? "best" : ""}"><td>${esc(x.label)}</td><td>${bar(x.precision, "var(--series-1)")}</td><td>${bar(x.recall, "var(--series-2)")}</td>
      <td class="n">${x.f1.toFixed(3)}</td><td class="n">${x.roc_auc == null ? "—" : x.roc_auc.toFixed(3)}</td><td class="n">${esc(x.tp)} / ${esc(x.fp)} / ${esc(x.fn)}</td></tr>`).join("");
    const typ = e.typologies.map((t) => `<tr><td>${esc(t.typology.replace("_", " "))}</td><td class="n">${esc(t.flagged)} of ${esc(t.total)}</td><td class="n">${(t.rate * 100).toFixed(1)}%</td></tr>`).join("");
    const conf = e.origin.by_confidence.map((b) => `<tr><td>${esc(b.bucket)}</td><td class="n">${esc(b.correct)} of ${esc(b.total)}</td><td class="n">${b.accuracy == null ? "—" : (b.accuracy * 100).toFixed(1) + "%"}</td></tr>`).join("");
    const scen = e.scenarios.map((s) => `<tr class="row-link" data-go="#cases/${esc(s.best_case)}" tabindex="0"><td>${esc(s.scenario)}</td><td class="n">${esc(s.in_best_case)} of ${esc(s.transactions)}</td><td>${esc(s.best_case)}</td></tr>`).join("");
    html += `<div class="card" style="margin-top:16px"><h2>Detection against ground truth</h2>
      <p class="desc">${esc(e.transactions)} simulated transactions, ${esc(e.positives)} of them part of a laundering scenario. This capture was used for neither training nor tuning. Each row adds information to the one above; the last row uses both layers.</p>
      <div class="legend"><span style="--c:var(--series-1)">precision</span><span style="--c:var(--series-2)">recall</span></div>
      <div class="scroll"><table><thead><tr><th>Detector</th><th>Precision</th><th>Recall</th><th class="n">F1</th><th class="n">ROC-AUC</th><th class="n">TP / FP / FN</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="callout small" style="margin:14px 0 0">Results on simulated traffic show that the pipeline works end to end and that each stage adds something. They do not predict accuracy on real traffic.</p></div>
      <div class="grid g3" style="margin-top:16px">
        <div class="card"><h2>Flag rate by true typology</h2><p class="desc">“normal” is the false-positive rate.</p><table><thead><tr><th>Typology</th><th class="n">Flagged</th><th class="n">Rate</th></tr></thead><tbody>${typ}</tbody></table></div>
        <div class="card"><h2>Origin attribution</h2><p class="desc">First-seen IP equals the true origin in ${(e.origin.accuracy * 100).toFixed(1)}% of transactions. Below 0.50 the console reports “unresolved”.</p><table><thead><tr><th>Confidence</th><th class="n">Correct</th><th class="n">Accuracy</th></tr></thead><tbody>${conf}</tbody></table></div>
        <div class="card"><h2>Operations recovered</h2><p class="desc">Share of each simulated operation grouped into one case.</p><table><thead><tr><th>Scenario</th><th class="n">In one case</th><th>Case</th></tr></thead><tbody>${scen}</tbody></table></div>
      </div>`;
  } else {
    html += `<div class="card"><h2>Detection against ground truth</h2><p class="desc">No ground truth is available for this dataset, so accuracy cannot be measured here.</p></div>`;
  }
  const maxW = Math.max(...card.evidence.map((w) => Math.abs(w.weight)), 1e-9);
  const weights = card.evidence.map((w) => `<tr><td>${esc(w.label)}</td><td><div class="factor" style="grid-template-columns:minmax(0,1fr) 60px;padding:0;margin:0"><div class="track"><div class="bar ${w.weight >= 0 ? "raise" : "lower"}" style="left:${w.weight >= 0 ? 50 : 50 - Math.abs(w.weight) / maxW * 50}%;width:${Math.abs(w.weight) / maxW * 50}%"></div><div class="zero" style="left:50%"></div></div><div class="num">${signed(w.weight, 3)}</div></div></td><td class="n">${w.background.toFixed(3)}</td></tr>`).join("");
  html += `<div class="card" style="margin-top:16px"><h2>Model card</h2>
    <p class="desc">${esc(m.architecture)}. Trained on ${esc(m.training_data)}: ${num(m.gnn_train_transactions)} transactions for the GNN, ${num(m.fusion_train_transactions)} held-out transactions for risk fusion, ${num(m.origin_calibration_transactions)} for origin-confidence calibration.</p>
    <div class="scroll"><table><thead><tr><th>Evidence signal</th><th style="min-width:220px">Weight in the risk score (log-odds)</th><th class="n">Average in training traffic</th></tr></thead><tbody>${weights}</tbody></table></div>
    <p class="small" style="margin:12px 0 0">Model file ${esc(m.file)} · SHA-256 <span class="mono hash">${esc(m.sha256)}</span></p></div>`;
  $("panel-evaluation").innerHTML = html;
})();

/* ---------- method ---------- */
(function renderMethod() {
  const icon = (d) => `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
  const steps = [
    ["Ingest", "Bulk CSV, JSON, JSON Lines and XML are read from disk. Network announcements and ledger records arrive as separate files and are joined on the transaction ID.", `<path d="M12 3v12m0 0-4-4m4 4 4-4M4 17v3h16v-3"/>`],
    ["Attribute the origin", "The peer that announces a transaction first is its most likely origin. Lead time, agreement between sensors and how often that peer merely relays give a calibrated confidence.", `<circle cx="12" cy="12" r="3"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/>`],
    ["Resolve entities", "Addresses spent together belong to one owner, except inside mixing rounds. Peeling chains, equal-output mixing and fan-out structures are traced on the money-flow graph.", `<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M7.5 8 11 15.7M16.5 8 13 15.7M8.5 6h7"/>`],
    ["Score", "An Isolation Forest finds outliers. A GraphSAGE network reads each transaction with the ones that fund and spend it. A logistic model fuses both with the network-layer evidence.", `<path d="M4 19V9m5 10V5m5 14v-7m5 7V8"/>`],
    ["Explain", "The fusion model is linear, so each signal's Shapley contribution is exact. Every case lists what raised the score, what lowered it, and a hash of the record.", `<path d="M9 12l2 2 4-4"/><path d="M12 3l8 3v6c0 4.5-3.4 7.6-8 9-4.6-1.4-8-4.5-8-9V6z"/>`],
  ];
  $("panel-method").innerHTML = `<div class="steps">${steps.map(([t, d, i], n) => `<div class="step-card"><div class="no">0${n + 1}</div><div class="ico">${icon(i)}</div><h2>${esc(t)}</h2><p>${esc(d)}</p></div>`).join("")}</div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><h2>Why two layers</h2><p class="desc" style="margin-bottom:0">An exchange paying out withdrawals one at a time produces the same on-chain shape as a laundering peel chain: small payment, large remainder, re-spent within seconds. The ledger alone cannot tell them apart. The network layer can, because it shows who announced the transactions. That is why the fused score beats the graph model on its own.</p></div>
      <div class="card"><h2>Built for an air gap</h2><p class="desc" style="margin-bottom:0">No network call is made anywhere. Geo and ASN lookups use local files. All three models run on NumPy alone, so an offline install needs only a handful of packages and every line of the scoring code can be audited. This console is a single file with no external assets.</p></div>
    </div>
    <div class="card" style="margin-top:16px"><h2>Limits</h2><p class="desc" style="margin-bottom:0">The models are trained on simulated traffic and must be retrained on labelled real captures before operational use. First-seen attribution needs sensors connected to many peers and cannot see through Tor or a VPN: it reports the exit, not the sender. Mixing is also used lawfully, so a flag is a reason to look, not a finding. Every output is an investigative lead that needs corroboration.</p></div>`;
})();

/* ---------- footer ---------- */
(function renderFooter() {
  const m = DATA.meta;
  $("case-count").textContent = CASES.length;
  $("foot").innerHTML = `<span>Pipeline v${esc(m.pipeline_version)} · run ${esc(m.generated_at)} in ${esc(m.runtime_s)} s</span>` +
    m.sources.map((f) => `<span>${esc(f.file)} · ${esc(f.records)} records${f.sha256 ? ` · sha256 <span class="mono">${esc(f.sha256.slice(0, 12))}…</span>` : ""}</span>`).join("") +
    `<span>Student prototype for SIH 2026 PS 26146. Synthetic data; not an official system of any agency.</span>`;
})();

/* ---------- routing ---------- */
function route() {
  const [name, arg] = (location.hash.slice(1) || "overview").split("/");
  const panel = document.getElementById("panel-" + name) ? name : "overview";
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.panel === panel)));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + panel));
  if (panel === "cases") {
    if (arg && CASES.some((c) => c.case_id === arg) && arg !== state.selected) { state.selected = arg; renderCase(); }
    renderCaseList();
  }
  if (arg || location.hash === "") return;
  scrollTo(0, 0);
}
addEventListener("hashchange", route);
renderCase();
renderCaseList();
route();
