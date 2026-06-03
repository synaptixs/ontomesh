/* wizard/static/js/components/onboarding.js — P1.3
 *
 * First-run onboarding overlay.  Shown when the wizard loads with
 * an empty session (no domain name, no entities), so a brand-new
 * visitor isn't dropped into a blank Step 1 with no guidance.
 *
 * The user picks a starter template (telecom / healthcare / finance
 * / retail / etc.) and gets a populated session in seconds; or
 * dismisses and starts blank.  Either choice persists to
 * localStorage so the overlay doesn't re-appear next session.
 *
 *   import { Onboarding } from "/static/js/components/onboarding.js";
 *   Onboarding.maybeShow({
 *     session: window.session,
 *     onTemplatePicked: async (name) => { ... fetch + reload },
 *     onSkip: () => { ... continue with blank session },
 *   });
 */

const STORAGE_KEY = "ontomesh.onboarding.dismissed.v1";

const INDUSTRY_META = {
  telecom: {
    icon:  "📡",
    label: "Telecom",
    desc:  "TMF SID baseline. Network elements, services, alarms, "
         + "and customers — everything an operator already models.",
  },
  healthcare: {
    icon:  "🏥",
    label: "Healthcare",
    desc:  "Patients, providers, encounters, observations. Aligned "
         + "with FHIR-style entity boundaries.",
  },
  finance: {
    icon:  "💸",
    label: "Finance",
    desc:  "Accounts, transactions, instruments, counterparties — "
         + "with audit-grade lineage out of the box.",
  },
  manufacturing: {
    icon:  "🏭",
    label: "Manufacturing",
    desc:  "Equipment, work orders, batches, quality events. Plays "
         + "well with ISA-95 hierarchies.",
  },
  retail: {
    icon:  "🛒",
    label: "Retail",
    desc:  "Products, orders, customers, inventory. The canonical "
         + "starting point for e-commerce ontologies.",
  },
  energy_utilities: {
    icon:  "⚡",
    label: "Energy & Utilities",
    desc:  "Grid assets, meter readings, outages — utility / "
         + "smart-grid baseline.",
  },
  government: {
    icon:  "🏛",
    label: "Government",
    desc:  "Programs, beneficiaries, services, regulations.",
  },
  insurance: {
    icon:  "📋",
    label: "Insurance",
    desc:  "Policies, claims, parties, coverages.",
  },
  logistics_supply_chain: {
    icon:  "🚚",
    label: "Logistics",
    desc:  "Shipments, carriers, hubs, tracking events.",
  },
  pharmaceuticals: {
    icon:  "💊",
    label: "Pharmaceuticals",
    desc:  "Trials, compounds, batches, regulatory submissions.",
  },
};


export class Onboarding {

  // ── Public API ──────────────────────────────────────────────

  /**
   * Decide whether to show the overlay; if yes, render it.
   * Returns true if shown, false otherwise.
   */
  static async maybeShow({ session, onTemplatePicked, onSkip } = {}) {
    if (Onboarding._wasDismissed())     return false;
    if (!Onboarding._isEmpty(session))  return false;
    const templates = await Onboarding._loadTemplates();
    if (!templates.length) return false;       // backend not ready
    Onboarding._render(templates, onTemplatePicked, onSkip);
    return true;
  }

  /** Force-show the overlay, ignoring the dismissed flag. */
  static async showNow({ onTemplatePicked, onSkip } = {}) {
    const templates = await Onboarding._loadTemplates();
    Onboarding._render(templates, onTemplatePicked, onSkip);
  }

  static reset() {
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
  }

  // ── Internals ──────────────────────────────────────────────

  static _wasDismissed() {
    try { return localStorage.getItem(STORAGE_KEY) === "1"; }
    catch (_) { return false; }
  }

  static _setDismissed() {
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch (_) {}
  }

  static _isEmpty(session) {
    if (!session) return true;
    const noDomain   = !(session.domain && session.domain.name);
    const noEntities = !Array.isArray(session.entities)
                       || session.entities.length === 0;
    return noDomain && noEntities;
  }

  static async _loadTemplates() {
    try {
      const r = await fetch("/api/templates");
      if (!r.ok) return [];
      const data = await r.json();
      // /api/templates returns { templates: <user-visible>, hidden: [...],
      // all: <every template> }.  For first-run onboarding we use ALL —
      // a brand-new visitor doesn't yet have a landing-visibility
      // preference, and seeing all 10 starting points is better than
      // seeing one.
      const list = (data.all || data.templates || []).map(t => {
        const name = t.name || t;
        return {
          name,
          meta: INDUSTRY_META[name] || {
            icon: "📦",
            label: name.replace(/[-_]/g, " ")
                       .replace(/\b\w/g, c => c.toUpperCase()),
            desc:  t.description || "Starter template.",
          },
        };
      });
      // Order: known industries first (by INDUSTRY_META key order),
      // unknowns after.
      const known = Object.keys(INDUSTRY_META);
      list.sort((a, b) => {
        const ia = known.indexOf(a.name);
        const ib = known.indexOf(b.name);
        if (ia === -1 && ib === -1) return a.name.localeCompare(b.name);
        if (ia === -1) return 1;
        if (ib === -1) return -1;
        return ia - ib;
      });
      return list;
    } catch (e) {
      console.warn("[onboarding] failed to load templates:", e);
      return [];
    }
  }

  static _render(templates, onTemplatePicked, onSkip) {
    // Guard against duplicate inserts (Hot reload / re-init).
    if (document.getElementById("onb-root")) return;

    const root = document.createElement("div");
    root.id = "onb-root";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-labelledby", "onb-h");

    const cards = templates.map(t => `
      <button class="onb-card" type="button" data-name="${t.name}">
        <span class="onb-card-icon" aria-hidden="true">${t.meta.icon}</span>
        <span class="onb-card-title">${escapeHtml(t.meta.label)}</span>
        <span class="onb-card-desc">${escapeHtml(t.meta.desc)}</span>
        <span class="onb-card-cta">Use this template →</span>
      </button>
    `).join("");

    root.innerHTML = `
      <div class="onb-backdrop" data-close></div>
      <div class="onb-modal" tabindex="-1">
        <button class="onb-close" type="button"
                aria-label="Close onboarding" data-close>×</button>
        <header class="onb-head">
          <p class="onb-eyebrow">Welcome to Ontomesh</p>
          <h2 id="onb-h">Pick a starting point.</h2>
          <p class="onb-sub">
            Each template seeds your session with a real ontology
            (entities, events, relationships, sample CQs) you can
            edit step by step. You can also start with a blank
            session and build from scratch.
          </p>
        </header>
        <div class="onb-grid">${cards}</div>
        <footer class="onb-foot">
          <button class="onb-skip" type="button" data-skip>
            Start with a blank session →
          </button>
        </footer>
      </div>
    `;

    document.body.appendChild(root);

    // Trap focus inside the modal for accessibility.
    const modal = root.querySelector(".onb-modal");
    modal.focus();
    const focusables = root.querySelectorAll(
      "button:not([disabled]), [tabindex]:not([tabindex='-1'])"
    );
    const first = focusables[0], last = focusables[focusables.length - 1];
    root.addEventListener("keydown", e => {
      if (e.key === "Escape") { dismiss(); }
      else if (e.key === "Tab") {
        if (e.shiftKey && document.activeElement === first) {
          last.focus(); e.preventDefault();
        } else if (!e.shiftKey && document.activeElement === last) {
          first.focus(); e.preventDefault();
        }
      }
    });

    // Wire actions.
    root.addEventListener("click", async (e) => {
      const closeTarget = e.target.closest("[data-close]");
      if (closeTarget) { dismiss(); return; }

      const skipBtn = e.target.closest("[data-skip]");
      if (skipBtn) {
        Onboarding._setDismissed();
        teardown();
        if (typeof onSkip === "function") onSkip();
        return;
      }

      const card = e.target.closest(".onb-card");
      if (card) {
        const name = card.dataset.name;
        card.classList.add("is-loading");
        card.disabled = true;
        try {
          if (typeof onTemplatePicked === "function") {
            await onTemplatePicked(name);
          }
          Onboarding._setDismissed();
          teardown();
        } catch (err) {
          card.classList.remove("is-loading");
          card.disabled = false;
          console.warn("[onboarding] template load failed:", err);
          alert("Sorry — couldn't load that template. See console for details.");
        }
      }
    });

    function dismiss() {
      Onboarding._setDismissed();
      teardown();
      if (typeof onSkip === "function") onSkip();
    }

    function teardown() {
      root.classList.add("is-leaving");
      setTimeout(() => root.remove(), 180);
    }
  }
}


function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export default Onboarding;
