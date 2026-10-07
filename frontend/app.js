/* ============================================================
   GAVEL frontend — single-page courtroom app.
   No build step, no external dependencies. Serve with:
       python3 -m http.server 8080
   then open http://localhost:8080/

   NOTE: the page is served on :8080 while the API lives on :8000,
   so the backend must allow CORS (Access-Control-Allow-Origin).
   Alternatively, serve this directory FROM the backend.
   ============================================================ */

"use strict";

/* ---------------- configuration ---------------- */
const API_BASE = "";
// Escrow contract address shown in the "on-chain proof" panel.
// Placeholder until the contract is deployed; the backend may also
// return `escrow_address` inside the verdict object, which wins.
const ESCROW_CONTRACT_ADDRESS = "0x0000000000000000000000000000000000000000";

/* ---------------- the bench ---------------- */
const JUSTICES = [
  {
    key: "textualist",
    name: "The Textualist",
    tagline: "Strict contract wording — what does the agreement actually say?",
    color: "#5b8db8",
    icon: "\u00A7", // section mark
    match: ["textualist"],
  },
  {
    key: "consumer_advocate",
    name: "The Consumer Advocate",
    tagline: "Fairness and leverage — who held the power in this deal?",
    color: "#d99a2b",
    icon: "\uD83D\uDEE1", // shield
    match: ["consumer", "advocate"],
  },
  {
    key: "precedent_analyst",
    name: "The Precedent Analyst",
    tagline: "Analogous cases — what has been decided before in situations like this?",
    color: "#3e8e5a",
    icon: "\uD83D\uDCDA", // books
    match: ["precedent", "analyst"],
  },
];

const PHASE_LABELS = {
  opening: "Opening Statements",
  rebuttal: "Rebuttals",
  closing: "Closing Arguments",
  vote: "Deliberation & Votes",
  verdict: "The Verdict",
};

/* ---------------- demo dispute ---------------- */
const DEMO_DISPUTE = {
  claimant_name: "Maya Chen",
  respondent_name: "Brightline Marketing LLC",
  claim_title: "Unpaid $500 invoice for website redesign",
  claim_description:
    "Freelancer Maya Chen completed a homepage + landing-page redesign for " +
    "Brightline Marketing LLC under a $500 fixed-fee statement of work. Final " +
    "files were delivered on March 14, 2026. After two rounds of revisions, the " +
    "client stopped responding. Invoice #INV-2026-041 ($500, Net-14) is now " +
    "60 days overdue, with no payment and no written dispute of the work.",
  amount_usdc: "500",
  claimant_evidence: [
    "Signed Statement of Work dated Feb 20, 2026 — $500 fixed fee, delivery March 14, Net-14 payment terms",
    "Delivery email with Figma handoff link, timestamped March 14, 2026 4:32 PM",
    'Client reply March 15: "looks great, just two small tweaks"',
    "Revision round 2 delivered March 18 — read receipt confirmed",
    "Invoice #INV-2026-041 sent March 20; two follow-up reminders, no response",
  ].join("\n"),
  respondent_evidence: [
    'Client claims the final design "didn\'t match the brand" — no written revision request on file',
    "Alleges delivery was 4 days late (no late-delivery clause in the SOW)",
    'States they hired another designer to "fix" the work — no invoice or proof provided',
  ].join("\n"),
};

/* ---------------- DOM helpers ---------------- */
const $ = (id) => document.getElementById(id);

function setAct(n) {
  [1, 2, 3].forEach((i) => {
    $("act-file").classList.toggle("active", false);
  });
  $("act-file").classList.toggle("active", n === 1);
  $("act-court").classList.toggle("active", n === 2);
  $("act-verdict").classList.toggle("active", n === 3);
  document.querySelectorAll(".step").forEach((el) => {
    const s = Number(el.dataset.step);
    el.classList.toggle("active", s === n);
    el.classList.toggle("done", s < n);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showFormError(msg) {
  const el = $("form-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}

/* ---------------- clerk (backend) status ---------------- */
let clerkOnline = false;

async function checkClerk() {
  setClerkStatus("checking");
  // Any HTTP response (even 404/405) proves the backend is listening.
  // Only a network-level failure means it is down.
  const probes = [API_BASE + "/api/health", API_BASE + "/api/disputes"];
  for (const url of probes) {
    try {
      await fetch(url, { method: "GET" });
      clerkOnline = true;
      setClerkStatus("online");
      return;
    } catch (err) {
      // network-level failure — try the next probe
    }
  }
  clerkOnline = false;
  setClerkStatus("offline");
}

function setClerkStatus(state) {
  const pill = $("clerk-status");
  pill.className = "clerk-status " + state;
  $("clerk-status-text").textContent =
    state === "online" ? "Clerk: online" : state === "offline" ? "Clerk: unreachable" : "Checking clerk…";
  $("clerk-banner").classList.toggle("hidden", state !== "offline");
}

/* ---------------- justice bench ---------------- */
function buildBench() {
  const bench = $("bench");
  bench.innerHTML = "";
  JUSTICES.forEach((j) => {
    const card = document.createElement("div");
    card.className = "justice-card";
    card.id = "justice-" + j.key;
    card.style.setProperty("--jc", j.color);
    card.innerHTML =
      '<div class="justice-icon" aria-hidden="true">' + escapeHtml(j.icon) + "</div>" +
      "<h3>" + escapeHtml(j.name) + "</h3>" +
      '<p class="justice-tag">' + escapeHtml(j.tagline) + "</p>" +
      '<div class="justice-vote" id="vote-' + j.key + '"></div>';
    bench.appendChild(card);
  });
}

function matchJustice(persona) {
  if (!persona) return null;
  const p = String(persona).toLowerCase();
  return JUSTICES.find((j) => j.match.some((m) => p.includes(m))) || null;
}

function setSpeaking(key, on) {
  const card = key && $("justice-" + key);
  if (card) card.classList.toggle("speaking", on);
}

function setVote(key, side) {
  const el = key && $("vote-" + key);
  if (!el) return;
  const s = String(side || "").toLowerCase();
  if (s.includes("claimant")) el.textContent = "⚖ Votes: Claimant";
  else if (s.includes("respondent")) el.textContent = "⚖ Votes: Respondent";
  else if (side) el.textContent = "⚖ " + side;
}

/* ---------------- transcript (typewriter queue) ---------------- */
const speechQueue = [];
let speechBusy = false;
let lastRound = null;
let streamFinished = false;

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function transcriptEl() {
  return $("transcript");
}

function scrollTranscript() {
  const t = transcriptEl();
  t.scrollTop = t.scrollHeight;
}

function phaseLabel(type) {
  return PHASE_LABELS[type] || (type ? titleCase(String(type)) : "Deliberation");
}

function titleCase(s) {
  return s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function maybeInsertRoundMarker(round, type) {
  const r = round == null ? "?" : String(round);
  if (r === lastRound) return;
  lastRound = r;
  const marker = document.createElement("div");
  marker.innerHTML =
    '<div class="round-marker">Round ' + escapeHtml(r) + "</div>" +
    '<div class="round-phase">' + escapeHtml(phaseLabel(type)) + "</div>";
  transcriptEl().appendChild(marker);
  scrollTranscript();
}

function enqueueSpeech(evt) {
  speechQueue.push(evt);
  pumpSpeech();
}

function pumpSpeech() {
  if (speechBusy) return;
  const evt = speechQueue.shift();
  if (!evt) return;
  speechBusy = true;
  typeSpeech(evt, () => {
    speechBusy = false;
    pumpSpeech();
  });
}

function typeSpeech(evt, done) {
  const justice = matchJustice(evt.persona);
  const label = justice ? justice.name : evt.persona || "The Court";

  maybeInsertRoundMarker(evt.round, evt.type);

  const article = document.createElement("article");
  article.className = "speech";
  const chipColor = justice ? justice.color : "#8a7a5a";
  article.innerHTML =
    '<div class="speech-head">' +
    '<span class="speaker-chip" style="--jc:' + chipColor + '">' + escapeHtml(label) + "</span>" +
    '<span class="speech-type">' + escapeHtml(phaseLabel(evt.type)) + "</span>" +
    "</div>" +
    '<p class="speech-text"><span class="typed"></span><span class="caret"></span></p>';
  transcriptEl().appendChild(article);
  scrollTranscript();

  if (justice) setSpeaking(justice.key, true);

  const full = String(evt.text || "");
  const typed = article.querySelector(".typed");
  // Reveal word-by-word: brisk enough to feel live, robust for long text.
  const words = full.split(/(\s+)/);
  let i = 0;
  const CHUNK = 4;
  const timer = setInterval(() => {
    let html = "";
    const end = Math.min(i + CHUNK, words.length);
    for (let k = 0; k < end; k++) html += escapeHtml(words[k]);
    typed.innerHTML = html;
    i = end;
    scrollTranscript();
    if (i >= words.length) {
      clearInterval(timer);
      const caret = article.querySelector(".caret");
      if (caret) caret.remove();
      if (justice) setSpeaking(justice.key, false);
      if (evt.type === "vote") setVote(justice && justice.key, evt.text);
      done();
    }
  }, 28);
}

function showStreamError(msg) {
  const el = $("stream-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}

/* ---------------- API ---------------- */
async function apiPost(path, body) {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("HTTP " + res.status + " on POST " + path);
  return res.json();
}

async function apiGet(path) {
  const res = await fetch(API_BASE + path);
  if (!res.ok) throw new Error("HTTP " + res.status + " on GET " + path);
  return res.json();
}

/* ---------------- dispute flow ---------------- */
let currentDisputeId = null;
let eventSource = null;
let verdictRendered = false;

function parseEvidence(textareaId) {
  return $(textareaId)
    .value.split("\n")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

async function handleSubmit(e) {
  e.preventDefault();
  $("form-error").classList.add("hidden");

  const payload = {
    claimant_name: $("claimant-name").value.trim(),
    respondent_name: $("respondent-name").value.trim(),
    claim_title: $("claim-title").value.trim(),
    claim_description: $("claim-description").value.trim(),
    amount_usdc: parseFloat($("amount-usdc").value),
    claimant_evidence: parseEvidence("claimant-evidence"),
    respondent_evidence: parseEvidence("respondent-evidence"),
  };

  if (!payload.claimant_name || !payload.respondent_name || !payload.claim_title || !payload.claim_description) {
    showFormError("Please fill in all fields so the court has a complete record.");
    return;
  }
  if (!isFinite(payload.amount_usdc) || payload.amount_usdc <= 0) {
    showFormError("Please enter a valid dispute amount greater than zero.");
    return;
  }

  const btn = $("submit-btn");
  btn.disabled = true;
  $("submit-label").textContent = "Filing with the clerk…";

  try {
    const created = await apiPost("/api/disputes", payload);
    const id = created && (created.id || created.dispute_id);
    if (!id) throw new Error("Backend did not return a dispute id.");
    clerkOnline = true;
    setClerkStatus("online");
    startDeliberation(id, payload);
  } catch (err) {
    clerkOnline = false;
    setClerkStatus("offline");
    showFormError(
      "The court clerk is unreachable — is the backend running on :8000? (" + err.message + ")"
    );
  } finally {
    btn.disabled = false;
    $("submit-label").textContent = "Bring the case to court";
  }
}

function startDeliberation(id, payload) {
  currentDisputeId = id;
  verdictRendered = false;
  streamFinished = false;
  lastRound = null;
  speechQueue.length = 0;
  transcriptEl().innerHTML = "";
  $("stream-error").classList.add("hidden");
  buildBench();

  $("case-caption").textContent =
    payload.claimant_name + "  v.  " + payload.respondent_name +
    "  —  $" + Number(payload.amount_usdc).toFixed(2) + " USDC";
  $("phase-text").textContent = "The court is in session…";
  setAct(2);

  // Kick off the deliberation. We don't block the transcript on it:
  // the SSE stream carries the live debate, and this promise is our
  // fallback source for the verdict if the stream fails.
  const deliberatePromise = apiPost("/api/disputes/" + encodeURIComponent(id) + "/deliberate", {})
    .catch((err) => {
      console.warn("deliberate failed:", err);
      return null;
    });

  connectStream(id, deliberatePromise);
}

function connectStream(id, deliberatePromise) {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  let sawEvent = false;

  const url = API_BASE + "/api/disputes/" + encodeURIComponent(id) + "/stream";
  const es = new EventSource(url);
  eventSource = es;

  es.onmessage = (msg) => {
    sawEvent = true;
    let evt;
    try {
      evt = JSON.parse(msg.data);
    } catch (err) {
      console.warn("unparseable SSE payload:", msg.data);
      return;
    }
    handleStreamEvent(evt, deliberatePromise);
  };

  es.onerror = () => {
    // EventSource auto-retries; only treat as fatal once it gives up.
    if (es.readyState === EventSource.CLOSED) {
      finishStreamFallback(sawEvent, deliberatePromise);
    }
  };
}

function handleStreamEvent(evt, deliberatePromise) {
  if (!evt || typeof evt !== "object") return;
  const type = String(evt.type || "").toLowerCase();

  if (type === "verdict") {
    $("phase-text").textContent = "The verdict is in.";
    // Let any queued speeches finish, then render the verdict from the
    // authoritative GET (the event may only be a signal).
    const waitForQueue = () => {
      if (speechBusy || speechQueue.length) {
        setTimeout(waitForQueue, 300);
      } else {
        closeStream();
        finalizeFromServer();
      }
    };
    waitForQueue();
    return;
  }

  $("phase-text").textContent = phaseLabel(type) + (evt.round != null ? " — Round " + evt.round : "") + "…";
  enqueueSpeech(evt);
}

function closeStream() {
  streamFinished = true;
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

async function finishStreamFallback(sawEvent, deliberatePromise) {
  // Stream died. Prefer the deliberate() result; otherwise one last GET.
  closeStream();
  if (verdictRendered) return;
  let verdict = null;
  try {
    verdict = await deliberatePromise;
  } catch (err) {
    verdict = null;
  }
  if (verdict && hasVerdictShape(verdict)) {
    renderVerdict(verdict, null);
    return;
  }
  try {
    const full = await apiGet("/api/disputes/" + encodeURIComponent(currentDisputeId));
    const v = extractVerdict(full);
    if (v) {
      renderVerdict(v, full);
      return;
    }
  } catch (err) {
    console.warn("finalize GET failed:", err);
  }
  if (!sawEvent) {
    showStreamError(
      "The live transcript feed dropped before the court spoke. " +
      "The clerk may still be deliberating — try filing again, or check the backend logs."
    );
  } else {
    showStreamError("The transcript feed ended before a verdict arrived.");
  }
}

async function finalizeFromServer() {
  if (verdictRendered) return;
  try {
    const full = await apiGet("/api/disputes/" + encodeURIComponent(currentDisputeId));
    const v = extractVerdict(full);
    if (v) {
      renderVerdict(v, full);
      return;
    }
    showStreamError("The court adjourned without publishing a verdict. Please try again.");
  } catch (err) {
    showStreamError("Could not fetch the verdict from the clerk: " + err.message);
  }
}

/* ---------------- verdict ---------------- */
// The backend's verdict object shape may evolve; read it defensively.
function extractVerdict(dispute) {
  if (!dispute || typeof dispute !== "object") return null;
  const v = dispute.verdict || dispute.ruling || dispute;
  return hasVerdictShape(v) ? v : null;
}

function hasVerdictShape(v) {
  if (!v || typeof v !== "object") return false;
  return ["winner", "winning_side", "ruled_for", "reasoning", "summary", "decision"].some(
    (k) => v[k] != null
  );
}

function pick(obj, keys) {
  for (const k of keys) {
    if (obj[k] != null && obj[k] !== "") return obj[k];
  }
  return null;
}

function normalizeSide(v) {
  const w = String(pick(v, ["winner", "winning_side", "ruled_for", "decision"]) || "").toLowerCase();
  if (w.includes("claimant")) return "claimant";
  if (w.includes("respondent")) return "respondent";
  return null;
}

function renderVerdict(v, dispute) {
  if (verdictRendered) return;
  verdictRendered = true;
  closeStream();

  const side = normalizeSide(v);
  const banner = $("verdict-banner");
  banner.textContent = side === "respondent" ? "RULED FOR THE RESPONDENT" : "RULED FOR THE CLAIMANT";
  banner.classList.toggle("for-respondent", side === "respondent");

  const amount = pick(v, ["awarded_amount_usdc", "amount_awarded_usdc", "amount_awarded", "awarded_usdc", "award_usdc"]);
  const amountText = amount != null && isFinite(Number(amount))
    ? "Awarded: <strong>$" + Number(amount).toFixed(2) + " USDC</strong>"
    : "Awarded: <strong>as claimed</strong>";
  $("verdict-award").innerHTML = amountText;

  const reasoning = pick(v, ["reasoning", "summary", "rationale", "opinion", "explanation"]) || "No reasoning published.";
  $("verdict-reasoning").textContent = String(reasoning);

  // Per-justice votes, when the backend publishes them
  // (e.g. votes: [{persona, vote, justification}, ...]).
  if (Array.isArray(v.votes)) {
    v.votes.forEach((vt) => {
      if (!vt || typeof vt !== "object") return;
      const j = matchJustice(vt.persona);
      setVote(j && j.key, vt.vote);
    });
  }

  // Transcript hash — truncated display, full value on copy.
  const fullHash = pick(v, ["transcript_hash", "transcript_sha256", "hash", "sha256"]) ||
    (dispute && pick(dispute, ["transcript_hash", "transcript_sha256", "hash"]));
  const hashEl = $("transcript-hash");
  if (fullHash) {
    const h = String(fullHash);
    hashEl.textContent = h.length > 32 ? h.slice(0, 18) + "…" + h.slice(-10) : h;
    hashEl.title = h;
    hashEl.dataset.full = h;
    $("copy-hash").disabled = false;
  } else {
    hashEl.textContent = "not yet published";
    hashEl.title = "";
    hashEl.dataset.full = "";
    $("copy-hash").disabled = true;
  }

  // On-chain proof panel.
  const escrow = (dispute && pick(dispute, ["escrow_address", "contract_address"])) ||
    pick(v, ["escrow_address", "contract_address"]) || ESCROW_CONTRACT_ADDRESS;
  $("escrow-address").textContent = String(escrow);

  const tx = pick(v, ["tx_hash", "transaction_hash", "anchoring_tx", "anchor_tx"]) ||
    (dispute && pick(dispute, ["tx_hash", "transaction_hash", "anchoring_tx"]));
  const txEl = $("tx-hash");
  if (tx) {
    txEl.textContent = String(tx);
    txEl.classList.remove("pending");
    txEl.classList.add("anchored");
    $("chain-note").textContent = "The ruling hash is anchored on-chain; the escrow contract will auto-pay the winner.";
  } else {
    txEl.textContent = "pending on-chain anchoring";
    txEl.classList.add("pending");
    txEl.classList.remove("anchored");
    $("chain-note").textContent = "The ruling hash will be anchored on-chain and the escrow will auto-pay the winner.";
  }

  setAct(3);
}

/* ---------------- misc UI ---------------- */
function fillDemo() {
  $("claimant-name").value = DEMO_DISPUTE.claimant_name;
  $("respondent-name").value = DEMO_DISPUTE.respondent_name;
  $("claim-title").value = DEMO_DISPUTE.claim_title;
  $("claim-description").value = DEMO_DISPUTE.claim_description;
  $("amount-usdc").value = DEMO_DISPUTE.amount_usdc;
  $("claimant-evidence").value = DEMO_DISPUTE.claimant_evidence;
  $("respondent-evidence").value = DEMO_DISPUTE.respondent_evidence;
  $("form-error").classList.add("hidden");
  updateEscrowPreview();
  $("claimant-name").focus();
}

function updateEscrowPreview() {
  const amt = parseFloat($("amount-usdc").value);
  $("escrow-preview").textContent =
    isFinite(amt) && amt > 0 ? "$" + amt.toFixed(2) + " USDC" : "$0.00 USDC";
}

async function copyHash() {
  const full = $("transcript-hash").dataset.full || "";
  if (!full) return;
  const btn = $("copy-hash");
  try {
    await navigator.clipboard.writeText(full);
  } catch (err) {
    // Fallback for non-secure contexts (e.g. file://).
    const ta = document.createElement("textarea");
    ta.value = full;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { /* ignore */ }
    document.body.removeChild(ta);
  }
  const orig = btn.textContent;
  btn.textContent = "Copied ✓";
  setTimeout(() => { btn.textContent = orig; }, 1600);
}

function resetToFiling() {
  closeStream();
  speechQueue.length = 0;
  speechBusy = false;
  setAct(1);
}

function readFullTranscript() {
  // Jump back to the courtroom to re-read the streamed record.
  setAct(2);
}

/* ---------------- wire up ---------------- */
document.addEventListener("DOMContentLoaded", () => {
  $("dispute-form").addEventListener("submit", handleSubmit);
  $("demo-btn").addEventListener("click", fillDemo);
  $("amount-usdc").addEventListener("input", updateEscrowPreview);
  $("clerk-retry").addEventListener("click", checkClerk);
  $("copy-hash").addEventListener("click", copyHash);
  $("new-case-btn").addEventListener("click", resetToFiling);
  $("full-transcript-btn").addEventListener("click", readFullTranscript);
  buildBench();
  updateEscrowPreview();
  checkClerk();
});
