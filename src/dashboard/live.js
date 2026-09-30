/* ---------- live demo: capture replay + risk simulator ----------
   Loaded after console.js and uses its helpers (esc, num, btc, sev, ring, factorRows ...). */
const STREAM = DATA.stream || [];
const TH = DATA.model_card.thresholds;
const levelOf = (risk) => risk >= TH.critical ? "CRITICAL" : risk >= TH.high ? "HIGH" : risk >= TH.medium ? "MEDIUM" : "LOW";
const hms = (ts) => iso(ts).slice(11, 19);

const live = {
  i: 0, clock: STREAM.length ? STREAM[0].t : 0, playing: false, timer: null, seconds: 30,
  obs: 0, flagged: 0, resolved: 0, cases: new Map(), buckets: [],
};
const T0 = STREAM.length ? STREAM[0].t : 0, T1 = STREAM.length ? STREAM[STREAM.length - 1].t : 1;
const BINS = DATA.overview.timeline.length || 36, BIN_W = (T1 - T0) / BINS || 1;
const BIN_MAX = Math.max(1, ...DATA.overview.timeline.map((b) => b.total));

(function renderLiveShell() {
  $("panel-live").innerHTML = `
    <div class="card live-head">
      <div>
        <div class="eyebrow">Live demo</div>
        <h2 style="font-size:19px">Watch the system work through the capture</h2>
        <p class="desc" style="margin-bottom:0">Replays the recorded demo capture in arrival order, with the scores the pipeline gave each transaction. Transactions arrive, origins are attributed, and an alert opens the moment a laundering pattern is recognised.</p>
      </div>
      <div class="live-ctl">
        <button class="btn primary big" type="button" id="lv-play">▶ Run live demo</button>
        <button class="btn" type="button" id="lv-reset">↺ Reset</button>
        <div class="chips" role="group" aria-label="Replay speed">
          <button class="chip" type="button" data-sec="30" aria-pressed="true">Normal</button>
          <button class="chip" type="button" data-sec="10" aria-pressed="false">Fast</button>
        </div>
      </div>
    </div>
    <div class="live-bar"><div id="lv-progress"></div></div>
    <div class="live-stats">
      <div class="lstat"><span>Capture clock (UTC)</span><b id="lv-clock" class="mono">--:--:--</b></div>
      <div class="lstat"><span>Network observations</span><b id="lv-obs">0</b></div>
      <div class="lstat"><span>Transactions joined</span><b id="lv-tx">0</b></div>
      <div class="lstat"><span>Origins resolved</span><b id="lv-res">0</b></div>
      <div class="lstat"><span>Flagged</span><b id="lv-flag">0</b></div>
      <div class="lstat alert"><span>Alerts opened</span><b id="lv-cases">0</b></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><h2>Incoming transactions</h2><p class="desc">Newest first. Flagged transactions are marked with their severity.</p>
        <div class="feed" id="lv-feed"><div class="empty">Press “Run live demo” to start the replay.</div></div></div>
      <div class="card"><h2>Alerts</h2><p class="desc">One alert per operation. It grows as more of its transactions arrive; select it to open the case.</p>
        <div class="alerts" id="lv-alerts"><div class="empty">No alerts yet.</div></div></div>
    </div>
    <div class="card" style="margin-top:16px"><h2>Activity so far</h2>
      <div class="legend" style="margin-top:8px"><span style="--c:var(--series-1)">flagged</span><span style="--c:var(--context)">not flagged</span></div>
      <div class="cols" id="lv-cols"></div>
      <div class="axis-x"><span>${STREAM.length ? clock(T0) : ""}</span><span>${STREAM.length ? clock(T1) : ""}</span></div></div>
    <div id="sim"></div>`;
})();

function liveReset() {
  clearInterval(live.timer);
  Object.assign(live, {i: 0, clock: T0, playing: false, timer: null, obs: 0, flagged: 0, resolved: 0,
    cases: new Map(), buckets: Array.from({length: BINS}, () => [0, 0])});
  $("lv-feed").innerHTML = `<div class="empty">Press “Run live demo” to start the replay.</div>`;
  $("lv-alerts").innerHTML = `<div class="empty">No alerts yet.</div>`;
  $("lv-play").textContent = "▶ Run live demo";
  livePaint(true);
}

function livePaint(full) {
  $("lv-clock").textContent = live.i ? hms(Math.min(live.clock, T1)) : "--:--:--";
  $("lv-obs").textContent = num(live.obs);
  $("lv-tx").textContent = num(live.i);
  $("lv-res").textContent = num(live.resolved);
  $("lv-flag").textContent = num(live.flagged);
  $("lv-cases").textContent = num(live.cases.size);
  $("lv-progress").style.width = (STREAM.length ? (live.i / STREAM.length) * 100 : 0) + "%";
  if (!full) return;
  $("lv-cols").innerHTML = live.buckets.map(([total, flagged]) => `<div class="col">` +
    (flagged ? `<div class="seg flag" style="height:${(flagged / BIN_MAX) * 100}%"></div>` : "") +
    (total - flagged ? `<div class="seg rest" style="height:${((total - flagged) / BIN_MAX) * 100}%"></div>` : "") + `</div>`).join("");
}

function liveAlerts() {
  const items = [...live.cases.values()].sort((a, b) => b.last - a.last);
  $("lv-alerts").innerHTML = items.map((a) => {
    const c = CASES.find((k) => k.case_id === a.id), level = levelOf(a.peak);
    return `<a class="alert-card${a.fresh ? " fresh" : ""}" href="#cases/${esc(a.id)}" style="--c:${SEV_VAR[level]}">
      <div class="row"><span>${sev(level)} &nbsp;<b>${esc(a.id)}</b></span><span class="mono small">opened ${hms(a.first)}</span></div>
      <div>${esc(c ? c.typology : "")}</div>
      <div class="meter" style="--c:${SEV_VAR[level]}"><div style="width:${c ? (a.n / c.tx_count) * 100 : 0}%"></div></div>
      <div class="row small"><span>${a.n} of ${c ? c.tx_count : a.n} transactions seen</span><span>peak risk <b>${num(a.peak, 1)}</b></span></div></a>`;
  }).join("");
  items.forEach((a) => { a.fresh = false; });
}

function liveTick() {
  live.clock += (T1 - T0) / (live.seconds * 20);
  const rows = [];
  let alertsChanged = false;
  while (live.i < STREAM.length && STREAM[live.i].t <= live.clock) {
    const x = STREAM[live.i++];
    live.obs += x.o;
    if (x.ip) live.resolved++;
    const bucket = live.buckets[Math.min(BINS - 1, Math.floor((x.t - T0) / BIN_W))];
    bucket[0]++;
    const flagged = x.r >= TH.medium;
    if (flagged) { live.flagged++; bucket[1]++; }
    if (x.c) {
      let a = live.cases.get(x.c);
      if (!a) { a = {id: x.c, first: x.t, n: 0, peak: 0, fresh: true}; live.cases.set(x.c, a); }
      a.n++; a.last = x.t; a.peak = Math.max(a.peak, x.r);
      alertsChanged = true;
    }
    rows.push(`<div class="feed-row${flagged ? " hot" : ""}"><span class="mono">${hms(x.t)}</span><span class="mono">${esc(x.id)}…</span>
      <span class="net">${esc(x.n)}</span><span class="n">${esc(btc(x.v))}</span><span>${flagged ? sev(levelOf(x.r)) : `<span class="small">clear</span>`}</span><span class="n"><b>${num(x.r, 1)}</b></span></div>`);
  }
  if (rows.length) {
    const feed = $("lv-feed");
    if (feed.querySelector(".empty")) feed.innerHTML = "";
    feed.insertAdjacentHTML("afterbegin", rows.reverse().join(""));
    while (feed.children.length > 40) feed.lastElementChild.remove();
  }
  if (alertsChanged) liveAlerts();
  livePaint(rows.length > 0);
  if (live.i >= STREAM.length) {
    clearInterval(live.timer);
    live.playing = false;
    $("lv-play").textContent = "✓ Replay finished — run again";
    toast(`Replay finished: ${live.cases.size} alerts from ${num(STREAM.length)} transactions`);
  }
}

$("lv-play").addEventListener("click", () => {
  if (live.playing) {
    clearInterval(live.timer);
    live.playing = false;
    $("lv-play").textContent = "▶ Resume";
    return;
  }
  if (live.i >= STREAM.length) liveReset();
  live.playing = true;
  $("lv-play").textContent = "⏸ Pause";
  live.timer = setInterval(liveTick, 50);
});
$("lv-reset").addEventListener("click", liveReset);
$("panel-live").querySelectorAll("[data-sec]").forEach((chip) => chip.addEventListener("click", () => {
  live.seconds = Number(chip.dataset.sec);
  $("panel-live").querySelectorAll("[data-sec]").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
}));
liveReset();

/* ---------- risk simulator: the fusion model evaluated in the browser ---------- */
(function simulator() {
  const EV = DATA.model_card.evidence, BIAS = DATA.model_card.bias, BASE = DATA.model_card.base_value_log_odds;
  const sim = {gnn: 0.9, anomaly: 0.5, net: "origin_tor", hops: 12, coinjoin: 0, delay: 1, burst: 3};
  const PRESETS = {
    "Ordinary payment": {gnn: 0.03, anomaly: 0.45, net: "", hops: 0, coinjoin: 0, delay: 60, burst: 0},
    "Peel chain via Tor": {gnn: 0.9, anomaly: 0.5, net: "origin_tor", hops: 12, coinjoin: 0, delay: 1, burst: 3},
    "Same chain, from an exchange": {gnn: 0.9, anomaly: 0.5, net: "origin_exchange", hops: 12, coinjoin: 0, delay: 1, burst: 3},
    "CoinJoin via VPN": {gnn: 0.85, anomaly: 0.65, net: "origin_vpn", hops: 0, coinjoin: 0.5, delay: 5, burst: 1},
  };
  const NETS = [["", "Residential / mobile"], ["origin_tor", "Tor exit"], ["origin_vpn", "Commercial VPN"], ["origin_hosting", "Datacentre"], ["origin_exchange", "Known exchange"]];
  const slider = (key, label, min, max, step, unit) => `<label class="ctl"><span>${esc(label)} <b id="sv-${key}"></b>${unit ? " " + esc(unit) : ""}</span>
    <input type="range" id="s-${key}" min="${min}" max="${max}" step="${step}"></label>`;

  $("sim").innerHTML = `<div class="card" style="margin-top:16px">
    <div class="eyebrow">Try it yourself</div><h2 style="font-size:19px">Risk simulator</h2>
    <p class="desc">This is the real risk-fusion model, computed in your browser from its trained weights. Change the evidence and watch the score and its explanation move.</p>
    <div class="chips" id="sim-presets" style="margin-bottom:14px">${Object.keys(PRESETS).map((p) => `<button class="chip" type="button" data-preset="${esc(p)}">${esc(p)}</button>`).join("")}</div>
    <div class="sim-grid">
      <div class="sim-controls">
        ${slider("gnn", "GNN laundering probability", 0, 1, 0.01)}
        ${slider("anomaly", "Isolation Forest outlier score", 0, 1, 0.01)}
        <div class="ctl"><span>First-seen origin network</span><div class="chips" id="sim-net">${NETS.map(([k, l]) => `<button class="chip" type="button" data-net="${k}">${esc(l)}</button>`).join("")}</div></div>
        ${slider("hops", "Peeling chain length", 0, 16, 1, "hops")}
        ${slider("coinjoin", "Share of equal-valued outputs", 0, 1, 0.05)}
        ${slider("delay", "Funds re-spent after", 0, 60, 1, "min")}
        ${slider("burst", "Other transactions from the same IP within 10 min", 0, 15, 1)}
      </div>
      <div class="sim-out"><div class="sim-score" id="sim-score"></div><div id="sim-factors"></div><div class="equation" id="sim-eq"></div></div>
    </div></div>`;

  function values() {
    return {
      gnn_prob: sim.gnn, anomaly: sim.anomaly,
      origin_tor: +(sim.net === "origin_tor"), origin_vpn: +(sim.net === "origin_vpn"),
      origin_hosting: +(sim.net === "origin_hosting"), origin_exchange: +(sim.net === "origin_exchange"),
      peel_chain: sim.hops >= TH.peel_min_hops ? Math.min(1, Math.log2(1 + sim.hops) / 4) : 0,
      coinjoin: sim.coinjoin, velocity: Math.exp(-(sim.delay * 60) / 300),
      origin_burst: Math.min(1, Math.log2(1 + sim.burst) / 4),
    };
  }
  function paint() {
    ["gnn", "anomaly", "hops", "coinjoin", "delay", "burst"].forEach((k) => {
      $("s-" + k).value = sim[k];
      $("sv-" + k).textContent = Number.isInteger(sim[k]) ? sim[k] : sim[k].toFixed(2);
    });
    $("sim-net").querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.net === sim.net)));
    const x = values();
    let logit = BIAS;
    const factors = EV.map((e) => {
      const v = x[e.key] || 0, phi = e.weight * (v - e.background);
      logit += e.weight * v;
      return {factor: e.absent_label && v < 0.5 ? e.absent_label : e.label, value: v.toFixed(2), shap_log_odds: phi, share_pct: ""};
    }).sort((a, b) => Math.abs(b.shap_log_odds) - Math.abs(a.shap_log_odds));
    const risk = 100 / (1 + Math.exp(-logit)), level = levelOf(risk);
    $("sim-score").innerHTML = `${ring(risk, level)}<div><div>${sev(level)}</div>
      <div class="small" style="margin-top:4px">${level === "LOW" ? "Below the reporting threshold: not flagged." : "Would be flagged and grouped into a case."}</div></div>`;
    $("sim-factors").innerHTML = factorRows(factors);
    $("sim-eq").innerHTML = `<span>Base value <b>${signed(BASE)}</b></span><span>+ contributions <b>${signed(logit - BASE)}</b></span><span>= log-odds <b>${signed(logit)}</b></span><span>→ risk <b>${num(risk, 1)}</b></span>`;
  }
  ["gnn", "anomaly", "hops", "coinjoin", "delay", "burst"].forEach((k) => $("s-" + k).addEventListener("input", (ev) => {
    sim[k] = Number(ev.target.value);
    $("sim-presets").querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
    paint();
  }));
  $("sim-net").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    sim.net = c.dataset.net;
    $("sim-presets").querySelectorAll(".chip").forEach((p) => p.setAttribute("aria-pressed", "false"));
    paint();
  }));
  $("sim-presets").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    Object.assign(sim, PRESETS[c.dataset.preset]);
    $("sim-presets").querySelectorAll(".chip").forEach((p) => p.setAttribute("aria-pressed", String(p === c)));
    paint();
  }));
  $("sim-presets").querySelector('[data-preset="Peel chain via Tor"]').setAttribute("aria-pressed", "true");
  paint();
})();

/* ?autoplay starts the replay on load, for unattended screens */
if (new URLSearchParams(location.search).has("autoplay")) { location.hash = "#live"; $("lv-play").click(); }
