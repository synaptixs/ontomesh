/* wizard/static/js/components/proposal_card.js
 *
 * Reusable proposal-card renderer.
 *
 * The card is rendered for every PENDING / APPROVED / REJECTED row in
 * the Log Discovery review surface (Step 5). Every Tier 1/2/3 phase
 * has added a chip or badge here over the v3 cycle — regime tag (L8),
 * GP rate sparkline (L13), LLM rename (T1.1), shared causes (L11),
 * etc. Pulling it out of the inline template literal in index.html:
 *
 *   - cuts the page's HTML payload (no more 6 KB of string templates),
 *   - makes the next chip a one-line edit to KIND_BADGES / PILLS,
 *   - lets us add ARIA labels + keyboard semantics consistently,
 *   - keeps tests + future server-render swap a small refactor.
 *
 * Imported as an ES module from index.html:
 *
 *   <script type="module">
 *     import { renderProposalCard } from "{{ url_for('static',
 *           filename='js/components/proposal_card.js') }}";
 *     window.renderProposalCard = renderProposalCard;
 *   </script>
 */

// ── Kind metadata ───────────────────────────────────────────────────────

const KIND_BADGES = {
  LOG_EVENT:        { label: "Event",        bg: "#4338ca" },
  LOG_ENTITY:       { label: "Entity",       bg: "#0e7490" },
  LOG_RELATIONSHIP: { label: "Relationship", bg: "#0f766e" },
  LOG_CAUSAL_EDGE:  { label: "Causal edge",  bg: "#9333ea" },
};

const KINDS_WITH_GRAPH = new Set(["LOG_RELATIONSHIP", "LOG_CAUSAL_EDGE"]);


// ── HTML escape — single source of truth for the card ───────────────────

const HTML_ESCAPE = { "<": "&lt;", ">": "&gt;", "&": "&amp;",
                       '"': "&quot;", "'": "&#39;" };

export function escapeHtml(s) {
  return String(s || "").replace(/[<>&"']/g, ch => HTML_ESCAPE[ch]);
}


// ── Sparkline ──────────────────────────────────────────────────────────

/**
 * Render an inline SVG sparkline from a JSON list of per-bin counts.
 * Used by GP_RATE_DEVIATION proposals (L13).
 *
 * @param {string|number[]} raw  - either the JSON-encoded list or the
 *                                 list itself; the API stores it as a
 *                                 TEXT column.
 * @returns {string} - SVG markup, or "" when the input is malformed.
 */
export function renderSparkline(raw) {
  let arr;
  try { arr = typeof raw === "string" ? JSON.parse(raw) : raw; }
  catch (_) { return ""; }
  if (!Array.isArray(arr) || !arr.length) return "";
  const w = 80, h = 20;
  const max = Math.max(...arr) || 1;
  const dx = w / Math.max(1, arr.length - 1);
  const pts = arr.map((v, i) =>
    `${(i * dx).toFixed(1)},${(h - (v / max) * h).toFixed(1)}`
  ).join(" ");
  return (
    `<svg width="${w}" height="${h}" class="card-sparkline" ` +
    `role="img" aria-label="rate sparkline, ${arr.length} bins">` +
    `<polyline points="${pts}" fill="none" stroke="#16a34a" ` +
    `stroke-width="1.2"/></svg>`
  );
}


// ── Pills — one row of small badges to the left of the title ───────────

/**
 * Compute the ordered list of small status pills for a proposal.
 * Each pill is rendered as a <span class="card-pill ..."> with a
 * tooltip; the keys here drive both the visual and the aria-label
 * surfaces so keyboard / screen-reader users see the same info.
 */
function buildPills(c) {
  const pills = [];
  if (c.regime_tag) {
    pills.push({
      cls:   "card-pill card-pill-amber",
      title: "L8 — regime-aware HMM",
      text:  c.regime_tag,
    });
  }
  if (c.detection_strategy === "GP_RATE_DEVIATION") {
    pills.push({
      cls:   "card-pill card-pill-green",
      title: "L13 — GP rate anomaly",
      text:  "GP rate",
    });
  }
  // Future: more pills (T2.4 SHACL-redundant, T2.2 library-bootstrap, …)
  // each ships as one entry here. No card-renderer edit needed.
  return pills;
}

function renderPills(pills) {
  return pills.map(p =>
    `<span class="${p.cls}" title="${escapeHtml(p.title)}">` +
    `${escapeHtml(p.text)}</span>`
  ).join("");
}


// ── Action buttons ─────────────────────────────────────────────────────

/**
 * Compute the action-button row for a proposal. PENDING rows get the
 * full Approve / Reject / Edit / Merge row + the conditional "Show
 * endpoints" button for relationship-like kinds. Non-PENDING rows get
 * a status-summary span.
 *
 * Buttons carry aria-label attributes so screen readers announce
 * "Approve proposal foo-bar" instead of just "✓ Approve".
 */
function renderActions(c) {
  const pid = c.proposal_id;
  const isPending = c.status === "PENDING";
  if (!isPending) {
    return (
      `<span class="card-status-summary">${escapeHtml(c.status || "")}` +
      ` — ${escapeHtml((c.detection_strategy || "").replace(/_/g, " ").toLowerCase())}` +
      `</span>`
    );
  }
  const title = escapeHtml(c.title || "");
  const showGraph = KINDS_WITH_GRAPH.has(c.kind);
  return (
    `<button class="btn btn-primary card-btn" ` +
    `onclick="approveLogCandidate('${escapeHtml(pid)}')" ` +
    `aria-label="Approve ${title}">✓ Approve</button>` +

    `<button class="btn btn-ghost card-btn" ` +
    `onclick="rejectLogCandidate('${escapeHtml(pid)}')" ` +
    `aria-label="Reject ${title}">✕ Reject</button>` +

    `<button class="btn btn-ghost card-btn" ` +
    `onclick="editLogCandidate('${escapeHtml(pid)}')" ` +
    `aria-label="Edit ${title}">✎ Edit</button>` +

    `<button class="btn btn-ghost card-btn" ` +
    `onclick="mergeLogCandidate('${escapeHtml(pid)}')" ` +
    `aria-label="Merge ${title}">🔀 Merge</button>` +

    (showGraph
      ? `<button class="btn btn-ghost card-btn card-btn-graph" ` +
        `onclick="renderLogMiniGraph('${escapeHtml(pid)}')" ` +
        `aria-label="Show endpoint graph for ${title}">` +
        `👁 Show endpoints</button>`
      : "")
  );
}


// ── Top-level renderer ─────────────────────────────────────────────────

/**
 * Render one proposal card.
 *
 * @param {object} c  - the candidate row from /api/log-discovery/candidates.
 *                      Expected fields: kind, proposal_id, status, title,
 *                      confidence_score, evidence_sample, regime_tag (?),
 *                      detection_strategy, rate_sparkline (?).
 * @returns {string} - the card HTML.
 *
 * The card has three rows:
 *   1. Badge + pills + title + (optional) sparkline + confidence bar
 *   2. (optional) sample line
 *   3. (optional) mini-graph placeholder + action buttons
 *
 * `<div role="article">` plus `aria-label="<kind> proposal <title>"` so
 * screen readers and keyboard users can navigate between cards.
 */
export function renderProposalCard(c) {
  const kindMeta = KIND_BADGES[c.kind] || { label: c.kind, bg: "var(--muted)" };
  const conf = Math.round((c.confidence_score || 0) * 100);
  const sample = (c.evidence_sample || "").toString().slice(0, 120);
  const showGraph = KINDS_WITH_GRAPH.has(c.kind) && c.status === "PENDING";
  const titleEsc = escapeHtml(c.title || "");
  const ariaLabel = `${kindMeta.label} proposal: ${titleEsc}`;

  return `
    <div class="card card-proposal"
         id="log-disco-row-${escapeHtml(c.proposal_id)}"
         role="article"
         aria-label="${ariaLabel}">
      <div class="card-row card-row-header">
        <span class="card-kind-badge"
              style="background:${kindMeta.bg};color:white">${escapeHtml(kindMeta.label)}</span>
        ${renderPills(buildPills(c))}
        <span class="card-title">${titleEsc}</span>
        ${c.rate_sparkline ? renderSparkline(c.rate_sparkline) : ""}
        <div class="card-confidence" aria-label="confidence ${conf}%">
          <div class="card-confidence-track">
            <div class="card-confidence-fill" style="width:${conf}%"></div>
          </div>
          <span class="card-confidence-text">${conf}%</span>
        </div>
      </div>
      ${sample ? `<div class="card-sample">${escapeHtml(sample)}</div>` : ""}
      ${showGraph ? `<div id="log-disco-mini-${escapeHtml(c.proposal_id)}"
                            class="card-mini-graph"></div>` : ""}
      <div class="card-row card-row-actions">
        ${renderActions(c)}
      </div>
    </div>`;
}


// Exported for tests + future use; the inline JS still has its own
// _renderLogDiscoveryRow that delegates here for backwards-compat
// during the transition.
export default renderProposalCard;
