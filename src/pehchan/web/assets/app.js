/* Pehchan web client. All record and user text is inserted with textContent, never as HTML. */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const TOKEN_KEY = "pehchan-write-token";

  function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function token() {
    try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
  }

  async function api(method, path, body, { write = false } = {}) {
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (write && token()) headers.Authorization = "Bearer " + token();
    const response = await fetch(path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try { data = await response.json(); } catch { /* non-JSON error page */ }
    if (!response.ok) {
      const error = new Error((data && data.detail) || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function setStatus(message, { busy = false, error = false } = {}) {
    const status = $("#status");
    status.className = "status" + (error ? " error" : "");
    status.replaceChildren(busy ? el("span", { class: "spinner", "aria-hidden": "true" }) : "", message);
  }

  const PROVIDER_NAMES = { openrouter: "OpenRouter", google_ai_studio: "Google AI Studio" };
  const MODEL_NAMES = {
    "openai/gpt-oss-120b": "GPT-OSS 120B",
    "google/gemma-4-31b-it": "Gemma 4 31B",
    "gemma-4-31b-it": "Gemma 4 31B",
    "gemma-4-26b-a4b-it": "Gemma 4 26B",
    "google/gemma-4-26b-a4b-it": "Gemma 4 26B",
  };

  // Plain-language name for whatever answered this investigation.
  function engineLabel(inference) {
    const model = MODEL_NAMES[inference.model] || inference.model;
    const provider = PROVIDER_NAMES[inference.provider] || inference.provider;
    switch (inference.mode) {
      case "graph_recall": return "Answered from graph memory";
      case "gemini":
      case "openrouter": return `AI agent: ${model} via ${provider}`;
      case "deterministic_fallback": return "Offline agents (AI model busy)";
      default: return "Offline agents";
    }
  }

  const unquote = (text) => (text || "").trim().replace(/^["“”]+|["“”]+$/g, "");
  const truncate = (text, n) => (text.length > n ? text.slice(0, n - 1) + "…" : text);

  // ---------- result rendering ----------
  const FINDINGS = {
    KNOWN_RECYCLED_CLAIM: ["recycled", "Known recycled claim"],
    KNOWN_NARRATIVE_VARIANT: ["narrative", "Variant of a known narrative"],
    NEW_CLAIM: ["new", "New claim"],
  };
  const STATUS = {
    EVIDENCE_DOSSIER_READY: "Evidence dossier ready",
    NEEDS_HUMAN_REVIEW: "Human review needed",
    INSUFFICIENT_EVIDENCE: "Evidence is insufficient",
  };

  function sourceCard({ publisher, rating, claim, url, meta, shared }) {
    return el("article", { class: "source" },
      el("div", { class: "source-top" },
        el("span", { class: "source-pub", text: publisher }),
        el("span", { class: "rating", text: truncate(rating || "Rating unavailable", 90), title: rating }),
      ),
      el("p", { class: "source-claim", text: unquote(claim) }),
      shared && shared.length
        ? el("div", { class: "shared" }, shared.map((s) => el("span", { class: "pill", text: s })))
        : null,
      el("div", { class: "source-meta" },
        meta ? meta + " · " : "",
        url ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: "Open the fact-check ↗" }) : null,
      ),
    );
  }

  function render(report, { saved = false } = {}) {
    const result = $("#result");
    const [kind, label] = FINDINGS[report.finding] || ["new", report.finding || report.status];
    const queue = report.review_queue || {};
    const mode = (report.inference || {}).mode;
    const prior = report.prior_submission;

    const banner = el("section", { class: `finding ${kind}`, "aria-label": "Finding" },
      el("p", { class: "eyebrow", text: STATUS[report.status] || report.status }),
      el("h3", { class: "finding-label", text: label }),
      el("p", { text: queue.reason || report.recommended_action }),
      el("div", { class: "pills" },
        el("span", { class: "pill", text: `${report.quality.direct_reviews} direct review(s)` }),
        el("span", { class: "pill", text: `Priority ${report.priority}` }),
        el("span", { class: "pill", text: engineLabel(report.inference || {}), title: (report.inference || {}).hosted_error || "" }),
        saved && report.investigation_id ? el("span", { class: "pill", text: `Saved as ${report.investigation_id}` }) : null,
      ),
      prior && mode === "graph_recall"
        ? el("p", { class: "small", text: `Recalled through the graph: near-identical wording (similarity ${prior.similarity.toFixed(3)}) was investigated in ${prior.investigation_id}, so its MATCHES edges were followed instead of rerunning the models.` })
        : prior ? el("p", { class: "small", text: `Seen before in ${prior.investigation_id}.` }) : null,
    );

    const reply = report.draft_reply;
    const replyCard = reply
      ? el("section", { class: "card reply-card" },
          el("div", { class: "reply-head" },
            el("h3", { text: "Drafted reply" }),
            el("span", { class: "tag", text: "Needs human approval" }),
          ),
          el("p", { class: "reply-text", text: reply.text }),
          el("button", {
            class: "btn btn-small", type: "button",
            onclick: (e) => copyText(reply.text, e.currentTarget),
          }, "Copy reply"),
        )
      : null;

    const evidence = [];
    for (const c of report.citations || []) {
      evidence.push(sourceCard({
        publisher: c.publisher, rating: c.verdict_original, claim: c.reviewed_claim, url: c.url,
        meta: `${c.relevance.replaceAll("_", " ").toLowerCase()}${c.review_date ? " · " + c.review_date : ""}`,
      }));
    }
    const close = ((report.scout || {}).context || []).filter((c) => (c.similarity || 0) >= 0.6);
    for (const c of close.slice(0, 3)) {
      const source = (c.evidence || [])[0];
      if (!source) continue;
      evidence.push(sourceCard({
        publisher: source.publisher, rating: source.verdict_original, claim: c.text, url: source.url,
        meta: `closest recorded wording · similarity ${c.similarity.toFixed(2)} · ${c.assessment.relation.toLowerCase()} relevance`,
      }));
    }
    const related = ((report.widening || {}).related || []).slice(0, 4);
    const widened = related.map((r) => sourceCard({
      publisher: r.publisher, rating: r.verdict_original, claim: r.text, url: r.url,
      meta: `context score ${r.score.toFixed(3)}`,
      shared: [...new Set(r.shared.map((s) => `${s.label === "Entity" ? "Entity" : "Frame"}: ${s.name}`))],
    }));

    const evidenceCard = el("section", { class: "card" },
      el("h3", { text: "Published evidence" }),
      evidence.length
        ? el("div", { class: "sources" }, evidence)
        : el("p", { class: "muted", text: "No sufficiently relevant recorded review of this claim." }),
      widened.length ? el("h3", { text: "Widened through shared entities and frames", style: "margin-top:22px" }) : null,
      widened.length ? el("p", { class: "muted small", text: "These reviews concern related claims. They are context, not evidence for this message." }) : null,
      widened.length ? el("div", { class: "sources" }, widened) : null,
    );

    const timeline = el("ol", { class: "timeline" },
      (report.agent_trace || []).map((step, i) =>
        el("li", { style: `animation-delay:${i * 120}ms` },
          el("div", {},
            el("span", { class: "agent", text: step.agent }), " ",
            el("span", { class: "tool", text: step.tool || step.status }),
            step.duration_ms !== undefined ? el("span", { class: "muted small", text: ` · ${step.duration_ms} ms` }) : null,
            step.reason ? el("span", { class: "why", text: step.reason }) : null,
          ),
        ),
      ),
    );
    const note = (report.inference || {}).analyst_note;
    const traceCard = el("section", { class: "card" },
      el("h3", { text: "How the agents decided" }),
      note
        ? el("div", { class: "model-note" },
            el("span", { class: "tag", text: `${engineLabel(report.inference)} · note, not verified` }),
            el("p", { text: note }),
          )
        : null,
      timeline,
    );

    const uncertainties = el("details", { class: "card" },
      el("summary", { text: "Uncertainty and limits" }),
      el("ul", {}, [...(report.uncertainties || []), ...((report.quality || {}).warnings || [])].map((u) => el("li", { text: u }))),
    );

    const actions = el("div", { class: "result-actions" },
      !saved ? el("button", { class: "btn btn-primary", type: "button", onclick: (e) => save(report.submitted_claim, e.currentTarget.parentElement) },
        serverConfig.write_protected && !token() ? "Save as case (team only)" : "Save as case and remember it") : null,
      el("button", { class: "btn btn-ghost", type: "button", onclick: () => download(report) }, "Download dossier (JSON)"),
      el("a", { class: "btn btn-ghost", href: "#graph" }, "See it in the graph"),
    );

    result.replaceChildren(
      banner,
      el("div", { class: "result-grid" },
        el("div", { style: "display:grid;gap:20px" }, replyCard, evidenceCard),
        el("div", { style: "display:grid;gap:20px" }, traceCard, uncertainties),
      ),
      actions,
    );
    result.hidden = false;

    const focus = (report.citations || [])[0]?.variant_id || close[0]?.variant_id || related[0]?.variant_id;
    if (focus) {
      lastFocus = { id: focus, label: truncate(unquote(report.submitted_claim), 60) };
      loadGraph(focus, "Showing how your claim connects: the closest recorded claim is the large outlined dot, and its details are on the right.");
    } else {
      lastFocus = null;
      loadGraph(null, "Nothing in the graph connects to this claim yet, so it is new to Pehchan. Showing the whole collection instead.");
    }
  }

  async function investigate(claim) {
    const button = $("#run");
    button.disabled = true;
    $("#result").hidden = true;
    setStatus("Running the agents. The first run loads the local models and can take about 30 seconds.", { busy: true });
    try {
      const report = await api("POST", "/api/dossier", { claim });
      setStatus("");
      render(report);
      $("#result").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      setStatus(error.message, { error: true });
    } finally {
      button.disabled = false;
    }
  }

  let serverConfig = { public_read: false, write_protected: false };

  function teamOnlyNotice(claim, anchor) {
    document.querySelector(".notice")?.remove();
    const input = el("input", { type: "password", placeholder: "Team write token", "aria-label": "Team write token", autocomplete: "off" });
    const notice = el("div", { class: "notice", role: "note" },
      el("b", { text: "Saving is for the Pehchan team on this public demo." }),
      el("span", { class: "small", text: "Saving writes the message into the shared graph, so it is protected to keep the graph clean. Everything else on this page works without an account: run any claim, copy the reply, download the dossier." }),
      el("div", { class: "notice-row" }, input,
        el("button", {
          class: "btn btn-small", type: "button",
          onclick: () => {
            if (!input.value.trim()) return;
            try { sessionStorage.setItem(TOKEN_KEY, input.value.trim()); } catch { /* storage blocked */ }
            notice.remove();
            save(claim);
          },
        }, "Save with token"),
      ),
    );
    anchor.after(notice);
    input.focus();
  }

  async function save(claim, anchor) {
    if (serverConfig.write_protected && !token() && anchor) {
      teamOnlyNotice(claim, anchor);
      return;
    }
    const requestId = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now());
    setStatus("Saving the case and writing the submission into the graph…", { busy: true });
    try {
      const report = await api("POST", "/api/investigations", { claim, request_id: requestId }, { write: true });
      setStatus("Saved. Submit a reworded version of the same forward to see graph recall.");
      render(report, { saved: true });
    } catch (error) {
      if (error.status === 401 || error.status === 403) {
        try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ }
        setStatus("That token was not accepted, so the case was not saved.", { error: true });
        return;
      }
      setStatus(error.message, { error: true });
    }
  }

  function download(report) {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const link = el("a", { href: URL.createObjectURL(blob), download: (report.investigation_id || "pehchan-dossier") + ".json" });
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function copyText(text, button) {
    try {
      await navigator.clipboard.writeText(text);
      const original = button.textContent;
      button.textContent = "Copied";
      setTimeout(() => { button.textContent = original; }, 1400);
    } catch {
      window.prompt("Copy this:", text);
    }
  }

  // ---------- graph ----------
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const NODE_COLORS = {
    ClaimVariant: "--node-variant", Claim: "--node-claim", NarrativeFrame: "--node-frame",
    Entity: "--node-entity", FactCheck: "--node-fc", Publisher: "--node-pub",
    Submission: "--node-sub", Topic: "--node-frame", Investigation: "--node-sub",
  };
  let network = null;
  let lastFocus = null;
  let graphData = { nodes: [], edges: [] };
  const LABELLED = new Set(["NarrativeFrame", "Entity", "Topic"]);
  const KIND = {
    ClaimVariant: "Claim wording", Claim: "Claim", NarrativeFrame: "Narrative frame", Entity: "Entity",
    FactCheck: "Fact-check", Publisher: "Publisher", Submission: "Submitted message", Topic: "Topic",
    Investigation: "Investigation",
  };

  function setMode(variantId) {
    const mode = $("#graph-mode");
    mode.textContent = variantId && lastFocus ? `Focused on: "${lastFocus.label}"` : variantId ? "Focused on one claim" : "Collection overview";
    mode.classList.toggle("focused", Boolean(variantId));
    $("#graph-focus").hidden = !lastFocus || variantId === lastFocus.id;
  }

  async function showNode(nodeId) {
    const panel = $("#graph-panel");
    const node = graphData.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const links = graphData.edges
      .filter((e) => e.source === nodeId || e.target === nodeId)
      .map((e) => {
        const other = graphData.nodes.find((n) => n.id === (e.source === nodeId ? e.target : e.source));
        const arrow = e.source === nodeId ? "→" : "←";
        return `${arrow} ${e.type.replaceAll("_", " ").toLowerCase()} ${other ? truncate(other.label || other.id, 60) : ""} (${e.basis.replaceAll("_", " ")})`;
      });
    panel.replaceChildren(
      el("span", { class: "kind", text: KIND[node.type] || node.type }),
      el("h4", { text: unquote(node.label || node.id) }),
      links.length ? el("ul", {}, links.slice(0, 12).map((l) => el("li", { text: l }))) : null,
      node.type === "ClaimVariant"
        ? el("button", { class: "btn btn-small", type: "button", onclick: () => loadGraph(node.id, "Focused on the claim you selected.") }, "Focus the graph here")
        : null,
    );
    if (node.type === "ClaimVariant") {
      try {
        const sources = await api("GET", "/api/evidence/" + encodeURIComponent(node.id));
        if ($("#graph-panel h4")?.textContent !== unquote(node.label || node.id)) return;
        panel.append(...sources.map((s) => sourceCard({
          publisher: s.publisher, rating: s.verdict_original, claim: node.label, url: s.url,
          meta: s.review_date || "",
        })));
      } catch { /* evidence is optional detail */ }
    }
  }

  async function loadGraph(variantId, caption) {
    const canvas = $("#graph-canvas");
    if (!window.vis) { $("#graph-caption").textContent = "Graph library could not load."; return; }
    try {
      const params = new URLSearchParams({ limit: variantId ? "80" : "140" });
      if (variantId) params.set("variant_id", variantId);
      const data = await api("GET", "/api/graph?" + params);
      graphData = data;
      const focused = Boolean(variantId);
      const nodes = data.nodes.map((n) => ({
        id: n.id,
        label: n.id === variantId || LABELLED.has(n.type) || (focused && n.type === "ClaimVariant")
          ? truncate(unquote(n.label || n.id), n.id === variantId ? 48 : 30)
          : undefined,
        title: `${n.type}: ${n.label || n.id}`,
        shape: "dot",
        size: n.id === variantId ? 26 : n.type === "NarrativeFrame" || n.type === "Entity" ? 16 : 11,
        color: { background: css(NODE_COLORS[n.type] || "--node-pub"), border: css("--card"), highlight: { background: css("--signal"), border: css("--ink") } },
        font: { color: css("--ink"), face: "Inter", size: n.id === variantId ? 18 : 14, strokeWidth: 4, strokeColor: css("--card"), bold: n.id === variantId },
        borderWidth: 2,
      }));
      const edges = data.edges.map((e) => ({
        from: e.source, to: e.target,
        title: `${e.type} · ${e.basis}`,
        dashes: e.basis !== "source_record",
        color: { color: "rgba(35, 40, 66, .38)", highlight: css("--signal"), hover: css("--signal") },
        arrows: { to: { enabled: true, scaleFactor: 0.4 } },
        width: 1.4,
      }));
      const options = {
        physics: {
          solver: "forceAtlas2Based",
          stabilization: { iterations: 250, fit: true },
          forceAtlas2Based: { gravitationalConstant: focused ? -70 : -45, springLength: focused ? 120 : 90, avoidOverlap: 0.4 },
        },
        nodes: { scaling: { label: { drawThreshold: 2, maxVisible: 22 } } },
        interaction: { hover: true, tooltipDelay: 120, zoomSpeed: 0.6, keyboard: { enabled: true, bindToWindow: false } },
      };
      if (network) network.destroy();
      network = new window.vis.Network(canvas, { nodes, edges }, options);
      // Settle once, then freeze so the picture stops moving; dragging still works.
      network.once("stabilizationIterationsDone", () => {
        network.setOptions({ physics: false });
        if (variantId) network.selectNodes([variantId]);
      });
      network.on("click", (params) => { if (params.nodes.length) showNode(params.nodes[0]); });
      setMode(variantId);
      if (variantId) {
        showNode(variantId);
      }
      $("#graph-caption").textContent = `${caption || "Collection overview."} ${nodes.length} nodes, ${edges.length} links. Scroll to zoom, drag to move, click a dot for details.`;
    } catch (error) {
      $("#graph-caption").textContent = "Graph unavailable: " + error.message;
    }
  }

  // ---------- connect ----------
  function setupConnect() {
    const url = location.origin + "/public/mcp/";
    $("#mcp-url").textContent = url;
    $("#cfg-claude").textContent = `claude mcp add --transport http pehchan ${url}`;
    $("#cfg-gemini").textContent = JSON.stringify({ mcpServers: { pehchan: { httpUrl: url } } }, null, 2);
    document.querySelectorAll("[data-copy]").forEach((button) =>
      button.addEventListener("click", () => copyText($("#" + button.dataset.copy).textContent, button)));
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    tabs.forEach((tab) => tab.addEventListener("click", () => {
      tabs.forEach((t) => {
        const selected = t === tab;
        t.setAttribute("aria-selected", String(selected));
        $("#" + t.getAttribute("aria-controls")).hidden = !selected;
      });
    }));
  }

  // ---------- top bar status ----------
  function setPill(tone, text) {
    const pill = $("#status-pill");
    pill.dataset.tone = tone;
    $("#status-pill-text").textContent = text;
  }

  async function loadStats() {
    try {
      const health = await api("GET", "/health");
      document.querySelector('[data-stat="claims"]').textContent = health.claims;
      const ready = health.status === "ready";
      setPill(ready ? "pass" : "fail", ready ? "FalkorDB ready" : "setup required");
      const inference = health.inference || {};
      const chain = (inference.chain || []).map((c) => `${MODEL_NAMES[c.model] || c.model} via ${PROVIDER_NAMES[c.provider] || c.provider}`);
      $("#sp-graph").textContent = `graph: ${health.graph}`;
      $("#sp-engine").textContent = "FalkorDB · vector index · algo.SPpaths · algo.BFS";
      $("#sp-size").textContent = `${health.claims} claim wordings · ${health.embedded} embedded`;
      $("#sp-agent").textContent = chain.length ? chain.join(" → ") : "offline specialists";
      $("#sp-access").textContent = serverConfig.public_read ? "public read-only · writes need a token" : "local";
    } catch {
      setPill("fail", "API unreachable");
    }
  }

  function setupStatusPanel() {
    const pill = $("#status-pill");
    const panel = $("#status-panel");
    const close = () => { panel.hidden = true; pill.setAttribute("aria-expanded", "false"); };
    pill.addEventListener("click", (e) => {
      e.stopPropagation();
      panel.hidden = !panel.hidden;
      pill.setAttribute("aria-expanded", String(!panel.hidden));
    });
    document.addEventListener("click", (e) => { if (!panel.contains(e.target)) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  }

  // ---------- decorative motion: the highlight sweep and the diagram captions ----------
  function setupMotion() {
    const marks = document.querySelectorAll(".hl");
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => {
        for (const entry of entries) if (entry.isIntersecting) { entry.target.setAttribute("data-in", ""); io.unobserve(entry.target); }
      }, { rootMargin: "0px 0px -20% 0px" });
      marks.forEach((m) => io.observe(m));
    } else {
      marks.forEach((m) => m.setAttribute("data-in", ""));
    }
    const caption = $("#diagram-caption");
    const parts = document.querySelectorAll(".diagram .part");
    if (!caption || !parts.length) return;
    const idle = caption.innerHTML;
    const show = (part) => {
      parts.forEach((p) => p.removeAttribute("data-on"));
      part.setAttribute("data-on", "");
      // captions are authored in this file's markup, never from server or user data
      const [title, ...rest] = part.dataset.caption.replace(/<\/?b>/g, "\u0000").split("\u0000").filter(Boolean);
      caption.replaceChildren(el("b", { text: title }), rest.join(""));
    };
    const reset = () => { parts.forEach((p) => p.removeAttribute("data-on")); caption.innerHTML = idle; };
    parts.forEach((part) => {
      part.addEventListener("mouseenter", () => show(part));
      part.addEventListener("focus", () => show(part));
      part.addEventListener("click", () => show(part));
      part.addEventListener("mouseleave", reset);
      part.addEventListener("blur", reset);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupConnect();
    setupStatusPanel();
    setupMotion();
    api("GET", "/api/config").then((c) => { serverConfig = c; }).catch(() => { /* defaults */ }).finally(loadStats);
    $("#graph-fit").addEventListener("click", () => network && network.fit({ animation: true }));
    $("#graph-overview").addEventListener("click", () => loadGraph(null, "Collection overview."));
    $("#graph-focus").addEventListener("click", () => lastFocus && loadGraph(lastFocus.id, "Back to the closest recorded claim from your investigation."));
    loadGraph(null, "Collection overview.");
    document.querySelectorAll(".chip-example").forEach((chip) =>
      chip.addEventListener("click", () => { $("#claim").value = chip.dataset.claim; $("#claim").focus(); }));
    $("#claim-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const claim = $("#claim").value.trim();
      if (claim) investigate(claim);
    });
    // Shareable demo links: /?claim=... runs that investigation on load.
    const shared = new URLSearchParams(location.search).get("claim");
    if (shared) {
      $("#claim").value = shared.slice(0, 4000);
      investigate($("#claim").value.trim());
    }
  });
})();
