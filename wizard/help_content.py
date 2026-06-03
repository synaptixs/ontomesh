"""P0.4 — Per-phase help content for the wizard.

A flat ``HELP_PAGES`` dict, one entry per pipeline phase, consumed by the
shared ``phase_help.html`` template.  Each entry follows the same shape so
the renderer can stay dumb:

    {
        "slug":         <url segment>,
        "step_num":     "1" | "2" | ...,
        "title":        <page heading>,
        "tagline":      <one-line subtitle>,
        "what":         <what this phase does — markdown-free paragraphs>,
        "why":          <why it matters>,
        "capabilities": [(label, description), ...],
        "workflow":     [(step heading, body), ...],
        "tips":         [tip, tip, ...],
        "concepts":     [(term, gloss), ...],   # optional
        "next":         (slug, label),          # next help page
        "prev":         (slug, label),          # previous help page
    }

Phases are ordered to match the wizard's step navigation.

Note: 'log-discovery' (step 5) ships its own bespoke help page from
v3.0 — kept as-is at ``/log-discovery/help``.  Everything else uses
this shared system.
"""

from __future__ import annotations

# ---------------------------------------------------------------------- #
# Phase content                                                          #
# ---------------------------------------------------------------------- #

HELP_PAGES: dict[str, dict] = {

    # ── Step 1 — Domain Identity ───────────────────────────────────────
    "domain": {
        "slug":     "domain",
        "step_num": "1",
        "title":    "Domain Identity",
        "tagline":  "Anchor every ontology you build to a stable, "
                    "versioned identity.",
        "what": (
            "Domain Identity is the very first step of every wizard "
            "session. You declare the ontology's name, a base IRI, a "
            "short prefix, an authority (org / team), and an initial "
            "semantic version. The toolkit then stamps every artifact "
            "downstream — entities, events, rules, generated TTL, even "
            "vector indexes — with that identity so they can be linked, "
            "diffed, and audited across runs."
        ),
        "why": (
            "Without a stable identity, two ontologies that look the "
            "same become impossible to reconcile, version diffs leak "
            "into your downstream consumers, and compliance evidence "
            "loses its anchor. Capturing this once at the start removes "
            "an entire class of accidental incompatibilities."
        ),
        "capabilities": [
            ("Versioned base IRI",
             "Each release of the ontology gets its own dated namespace "
             "(e.g. /v2026-06/) so consumers can pin and upgrade."),
            ("Prefix registry",
             "Your chosen prefix is registered globally so it round-trips "
             "through Turtle, SHACL, and SPARQL."),
            ("Authority binding",
             "Couples the ontology to an org or team for downstream "
             "permissions and approval policies (T2.3)."),
            ("Imports declaration",
             "Optional FOAF / SKOS / Schema.org imports are recorded "
             "here and re-emitted in every generated TTL."),
        ],
        "workflow": [
            ("Name your ontology",
             "Pick a human-readable name; the slug is auto-derived."),
            ("Set the base IRI",
             "A unique HTTPS URL you control. The toolkit appends the "
             "version segment for you."),
            ("Choose a prefix",
             "3–6 characters; lower-case alphanumerics. Validated for "
             "uniqueness against the global registry."),
            ("Save",
             "Settings persist to the session DB; you can revisit "
             "and bump the version at any time."),
        ],
        "tips": [
            "Prefer dated version segments (v2026-06) over numeric ones "
            "(v1) — they sort lexicographically and survive forks.",
            "If you import an upstream ontology, declare it here once; "
            "the wizard auto-injects the owl:imports triple into every "
            "generated file.",
            "Prefixes are case-sensitive in SPARQL — pick a casing "
            "convention and stick to it.",
        ],
        "concepts": [
            ("Base IRI",
             "The stem all entity/event IRIs are built from."),
            ("Prefix",
             "Short alias for the base IRI used in Turtle and SPARQL."),
            ("Authority",
             "The org/team that owns and approves changes."),
        ],
        "next": ("entities", "Entities →"),
        "prev": None,
    },

    # ── Step 2 — Entities ──────────────────────────────────────────────
    "entities": {
        "slug":     "entities",
        "step_num": "2",
        "title":    "Entities",
        "tagline":  "Define the things — products, customers, orders, "
                    "anything noun-shaped — your domain talks about.",
        "what": (
            "Entities are the nouns of your ontology: the classes whose "
            "instances will populate the knowledge graph. Each entity "
            "gets a name, an optional parent class, a description, and "
            "any data properties (e.g. ``email: xsd:string``). The "
            "wizard can also infer entities from imported JSON Schemas, "
            "Avro contracts, or sample data — see T1.4 (schema-import "
            "depth)."
        ),
        "why": (
            "Entities are the spine of every downstream artifact. "
            "Relationships connect them; CQs query them; rules govern "
            "them. Getting this layer modeled correctly — neither too "
            "fine-grained nor too coarse — saves rework everywhere "
            "else."
        ),
        "capabilities": [
            ("Inheritance",
             "Single-parent inheritance with owl:subClassOf, automatically "
             "emitted to the generated TTL."),
            ("Data properties",
             "Typed attributes (xsd:string, xsd:integer, xsd:dateTime, "
             "xsd:decimal) with optional cardinality constraints."),
            ("Schema import",
             "Parse JSON Schema / Avro / Protobuf and propose entities + "
             "properties for one-click acceptance (T1.4)."),
            ("Naming AI-assist",
             "LLM-assisted suggestions for entity names that already "
             "exist on neighbouring concepts (T1.1)."),
        ],
        "workflow": [
            ("Optionally import",
             "Drop in a JSON Schema or Avro file to seed candidates."),
            ("Review candidates",
             "Each one shows confidence, source, and a one-click accept."),
            ("Edit / add",
             "Add free-form entities; pick parent classes from a "
             "type-ahead picker."),
            ("Annotate",
             "Add data properties and human-readable descriptions — both "
             "feed SHACL shapes and the Generated TTL."),
        ],
        "tips": [
            "Prefer composition over deep inheritance — owl:subClassOf "
            "chains beyond 3 levels become hard to query.",
            "Use singular nouns (Customer, not Customers).",
            "Data properties should be atomic; if a field has structure, "
            "lift it into its own entity.",
        ],
        "concepts": [
            ("Class",
             "An OWL class — the type of a set of individuals."),
            ("Data property",
             "A literal-valued attribute, e.g. email or birthDate."),
            ("Cardinality",
             "How many values a property may take per subject (0..1, "
             "1..1, 0..n)."),
        ],
        "next": ("events", "Events →"),
        "prev": ("domain", "← Domain Identity"),
    },

    # ── Step 3 — Events ────────────────────────────────────────────────
    "events": {
        "slug":     "events",
        "step_num": "3",
        "title":    "Events",
        "tagline":  "Capture the verbs — purchases, logins, sensor pings "
                    "— that link entities over time.",
        "what": (
            "Events represent things that happen. Each event has a "
            "name, a timestamp property, optional actor/target entities, "
            "and a payload schema. The toolkit promotes events to "
            "first-class citizens so causal discovery (L11 / T2.5) and "
            "regime modeling (L8) can reason over them directly."
        ),
        "why": (
            "Most enterprise data is event-shaped: orders placed, "
            "sessions started, alarms tripped. Modeling these as named "
            "events — rather than burying them in entity attributes — "
            "unlocks causal DAGs, sequence anomaly detection (T3.5), "
            "and proper time-aware queries."
        ),
        "capabilities": [
            ("Actor / target binding",
             "Events declare who performed them and what was affected; "
             "this becomes the basis for relationships."),
            ("Time-series tagging",
             "Events flagged as time-series feed Phase L8 (regime "
             "discovery) and L13 (rate-anomaly GPs)."),
            ("Payload schema",
             "Each event carries a strongly typed payload — same data "
             "model as entity properties."),
            ("Causal targets",
             "Events can be marked as treatments or outcomes for the "
             "interventional discovery in T2.5."),
        ],
        "workflow": [
            ("Add an event",
             "Name, timestamp property, and a short description."),
            ("Bind actor / target",
             "Pick existing entities; the wizard renders the implied "
             "relationships automatically."),
            ("Declare the payload",
             "Add typed properties just like an entity."),
            ("Tag for analysis",
             "Mark as time-series, treatment, or outcome to enable "
             "downstream phases."),
        ],
        "tips": [
            "Name events in past tense (OrderPlaced, not PlaceOrder) — "
            "they already happened.",
            "Every event should have a timestamp — without one, L8/L13 "
            "skip it.",
            "If two events fire together more than 95 % of the time, "
            "consider merging them; the causal discovery in L11 will "
            "otherwise produce a brittle DAG.",
        ],
        "next": ("relationships", "Relationships →"),
        "prev": ("entities", "← Entities"),
    },

    # ── Step 4 — Relationships ─────────────────────────────────────────
    "relationships": {
        "slug":     "relationships",
        "step_num": "4",
        "title":    "Relationships",
        "tagline":  "Wire entities and events together with typed, "
                    "domain-aware predicates.",
        "what": (
            "Relationships are OWL object properties: typed edges "
            "between an entity (or event) and another. Each carries "
            "a domain, range, cardinality, and an optional inverse. "
            "The toolkit also synthesizes relationships from event "
            "actor/target bindings so you rarely have to author them "
            "by hand."
        ),
        "why": (
            "Relationships are what turn a flat list of classes into "
            "a graph. They drive every SPARQL query, every SHACL shape, "
            "and every causal arrow. They are also where modelers "
            "spend most of their iteration time — so the wizard puts "
            "validation up-front."
        ),
        "capabilities": [
            ("Type-checked endpoints",
             "Domain/range pickers only show valid entity choices; "
             "violations are surfaced before save."),
            ("Inverse properties",
             "Declare an inverse once and both directions get "
             "owl:inverseOf triples in the generated TTL."),
            ("Functional / inverse-functional flags",
             "Promoted to OWL characteristics in the output, used by "
             "the reasoner in Phase 7."),
            ("Semantic diff (T2.4)",
             "Renames vs. deletions are distinguished automatically so "
             "evolution review doesn't ask the same question twice."),
        ],
        "workflow": [
            ("Pick endpoints",
             "Choose subject and object classes from the entity list."),
            ("Name the predicate",
             "Verb phrase (hasCustomer, placedBy) — the wizard suggests "
             "names based on neighbour relationships."),
            ("Set cardinality",
             "0..1 / 1..1 / 0..n / 1..n. Drives SHACL constraint "
             "emission."),
            ("Optionally declare an inverse",
             "If both directions are interesting (placedBy / placed)."),
        ],
        "tips": [
            "Verb-phrase predicates read better than noun-phrase ones — "
            "prefer hasOwner over ownerOf.",
            "Cardinality 1..1 is rare in messy data; prefer 0..1 with "
            "a soft SHACL warning unless you really mean it.",
            "If the same predicate appears between many class pairs, "
            "promote it to a top-level property with no domain — saves "
            "duplication.",
        ],
        "next": ("log-discovery", "Log Discovery →"),
        "prev": ("events", "← Events"),
    },

    # ── Step 6 — Competency Questions ──────────────────────────────────
    "cqs": {
        "slug":     "cqs",
        "step_num": "6",
        "title":    "Competency Questions",
        "tagline":  "Pin the questions your ontology must answer — and "
                    "auto-translate them to SPARQL.",
        "what": (
            "Competency Questions (CQs) are the unit tests of ontology "
            "engineering: natural-language questions the finished "
            "ontology must answer. The toolkit lets you author CQs, "
            "auto-translate them to SPARQL via T3.3, and run them "
            "against the live graph so you can watch coverage climb as "
            "you model."
        ),
        "why": (
            "Without CQs, you have no objective signal of whether the "
            "ontology is done. With them, every modeling decision can "
            "be justified by which CQ it makes answerable — and "
            "regressions surface immediately during evolution review."
        ),
        "capabilities": [
            ("CQ → SPARQL translation (T3.3)",
             "Few-shot prompted with your domain entities; the proposed "
             "SPARQL is editable before save."),
            ("Live evaluation",
             "Run all CQs at any time; pass/fail surfaces in the "
             "dashboard."),
            ("Coverage scoring",
             "Tracks how many CQs are answerable as you iterate."),
            ("CQ library",
             "Import canonical CQs from the cross-corpus template "
             "library (T2.2)."),
        ],
        "workflow": [
            ("Write a CQ in plain English",
             "\"Which customers placed more than three orders last "
             "month?\""),
            ("Review the auto-translation",
             "Toolkit emits SPARQL; you tweak prefixes / filters as "
             "needed."),
            ("Run it",
             "One-click execution against the live graph; row count "
             "and sample bindings render inline."),
            ("Save",
             "Persisted as a regression check for evolution review."),
        ],
        "tips": [
            "Aim for 10–30 CQs per ontology — fewer feels under-tested, "
            "more is hard to maintain.",
            "Group CQs by use case (sales, fraud, ops) so dashboards "
            "stay legible.",
            "If a CQ keeps failing because the SPARQL is wrong (not "
            "the model), edit the SPARQL — the translator learns from "
            "your edits in T3.3.",
        ],
        "next": ("rules", "Rules & Reasoning →"),
        "prev": ("log-discovery", "← Log Discovery"),
    },

    # ── Step 7 — Rules & Reasoning ─────────────────────────────────────
    "rules": {
        "slug":     "rules",
        "step_num": "7",
        "title":    "Rules & Reasoning",
        "tagline":  "Encode business logic as SHACL / SWRL / Datalog and "
                    "see what the reasoner derives.",
        "what": (
            "The Rules & Reasoning phase is where you encode domain "
            "logic that goes beyond pure structure: SHACL constraints "
            "for validation, SWRL or Datalog rules for derivation, and "
            "the T2.1 reasoner plug-ins that run them. Materialized "
            "triples are written to a separate output file so they "
            "stay separable from the asserted graph."
        ),
        "why": (
            "Rules turn an ontology from a passive vocabulary into an "
            "active knowledge system. SHACL catches data quality issues "
            "before they reach downstream systems; SWRL/Datalog derives "
            "new facts that would otherwise have to be hand-maintained."
        ),
        "capabilities": [
            ("SHACL shape editor",
             "Property-shape and node-shape authoring with live "
             "validation against sample data."),
            ("SWRL rule support",
             "Horn-clause rules with the standard SWRL built-ins."),
            ("Datalog (Rulewerk) plug-in (T2.1)",
             "Stratified Datalog with EDB / IDB separation; scales "
             "further than SWRL for large graphs."),
            ("Materialization report",
             "Every reasoner run emits a markdown report of derived "
             "triples and unsatisfied constraints."),
        ],
        "workflow": [
            ("Author shapes",
             "Use the SHACL editor or import an existing shapes file."),
            ("Add derivation rules",
             "Choose SWRL or Datalog from the rule editor's dropdown."),
            ("Run the reasoner",
             "One click triggers materialization; lineage is preserved."),
            ("Inspect the report",
             "Materialization report opens in a side panel; click a "
             "derived triple to see its provenance."),
        ],
        "tips": [
            "Use SHACL for constraints and SWRL/Datalog for derivations "
            "— mixing them in the same shape is a red flag.",
            "Always keep derived triples in a separate named graph so "
            "you can clear and re-materialize without touching the "
            "asserted graph.",
            "If a Datalog rule takes more than ~1 s, check whether the "
            "EDB predicate is indexed; T2.1 surfaces the slow predicates "
            "in the report.",
        ],
        "next": ("generate", "Generate →"),
        "prev": ("cqs", "← Competency Questions"),
    },

    # ── Step 8 — Generate ──────────────────────────────────────────────
    "generate": {
        "slug":     "generate",
        "step_num": "8",
        "title":    "Generate",
        "tagline":  "Emit the artifact bundle — Turtle, SHACL, JSON-LD, "
                    "Python bindings — in one click.",
        "what": (
            "Generate is the moment the in-memory model becomes files "
            "on disk. The toolkit emits a coordinated bundle: the OWL "
            "Turtle for the ontology itself, SHACL shapes for "
            "validation, JSON-LD contexts for application use, an "
            "optional Python `pydantic` binding layer, and the "
            "materialization report from Phase 7. T1.5 lets you "
            "emit multiple target formats from one model."
        ),
        "why": (
            "Most ontology projects die at this step — they generate "
            "one format manually and the other formats drift. Treating "
            "every target as a first-class output of the same model "
            "keeps them in lock-step forever."
        ),
        "capabilities": [
            ("Multi-target output (T1.5)",
             "OWL Turtle, SHACL, JSON-LD, RDF/XML, Python pydantic, "
             "TypeScript types — all from one model."),
            ("Deterministic byte-level output",
             "Same model + same version = same bytes. Critical for "
             "git diffs and compliance evidence."),
            ("Lineage materialization",
             "Derived triples carry prov:wasDerivedFrom; consumers "
             "can trace any fact back to its asserted source."),
            ("Bundle manifest",
             "Each generation writes a manifest.json with checksums "
             "for every artifact."),
        ],
        "workflow": [
            ("Pick targets",
             "Check the formats you need; the wizard remembers your "
             "last selection."),
            ("Pick the output directory",
             "Defaults to ``output/ontology/<version>/`` — versioned "
             "so older bundles aren't overwritten."),
            ("Generate",
             "Progress bar shows each format as it completes."),
            ("Review the manifest",
             "Inline summary lists every file, byte count, and "
             "SHA-256."),
        ],
        "tips": [
            "Commit the entire bundle directory to git — consumers can "
            "then pin to a commit and reproduce exactly.",
            "If a downstream tool wants RDF/XML, generate it here "
            "rather than converting at consumption time; the toolkit's "
            "emitter is canonical.",
            "Toggle the Python binding output on if you have a Python "
            "consumer — saves a lot of glue code.",
        ],
        "next": ("evolve", "Evolution Review →"),
        "prev": ("rules", "← Rules & Reasoning"),
    },

    # ── Step 9 — Evolution Review ──────────────────────────────────────
    "evolve": {
        "slug":     "evolve",
        "step_num": "9",
        "title":    "Evolution Review",
        "tagline":  "Diff this version against the last one with "
                    "semantic awareness, not just text changes.",
        "what": (
            "Evolution Review compares the current ontology against "
            "the previous published version using the T2.4 semantic "
            "diff: renames are detected as renames (not delete + add), "
            "subclass restructurings are recognized, and breaking "
            "changes are highlighted with downstream impact estimates."
        ),
        "why": (
            "Naive textual diffs of TTL are unreadable. Semantic diff "
            "tells you what actually changed — and what will break for "
            "consumers. Without it, ontology releases become "
            "high-anxiety events."
        ),
        "capabilities": [
            ("Rename detection (T2.4)",
             "Embedding-based matching identifies renamed entities and "
             "properties; suppresses noise in the diff."),
            ("Breaking-change classification",
             "Each change marked safe / minor / breaking based on "
             "OWL semantics."),
            ("Downstream impact",
             "Lists CQs, SHACL shapes, and Python bindings affected by "
             "each change."),
            ("Approval workflow (T2.3)",
             "Policy-based auto-approval for low-risk diffs; high-risk "
             "changes route to a designated reviewer."),
        ],
        "workflow": [
            ("Pick the baseline",
             "Defaults to the most recent published version."),
            ("Review the diff",
             "Grouped by entity → events → rules → CQs."),
            ("Resolve disputes",
             "Where the semantic differ wasn't sure (e.g. ambiguous "
             "rename), you confirm or override."),
            ("Approve or request changes",
             "Approval moves the version to Published; rejection "
             "returns to the relevant phase."),
        ],
        "tips": [
            "Always run Evolution Review before regenerating consumer "
            "bindings — it surfaces the breaking changes you'd "
            "otherwise discover at runtime.",
            "If T2.4 misses a rename, override the match — the "
            "embedding model learns from your overrides for the next "
            "diff.",
            "Auto-approval thresholds (T2.3) are per-policy; tune them "
            "by team rather than globally.",
        ],
        "next": ("comply", "Compliance Dashboard →"),
        "prev": ("generate", "← Generate"),
    },

    # ── Step 10 — Compliance Dashboard ─────────────────────────────────
    "comply": {
        "slug":     "comply",
        "step_num": "10",
        "title":    "Compliance Dashboard",
        "tagline":  "Continuous compliance with live regulation feeds "
                    "and audit-grade evidence trails.",
        "what": (
            "The Compliance Dashboard surfaces how your ontology and "
            "its derived data stand against the regulations you're "
            "subject to. T3.4 introduced continuous regulation diffs: "
            "the toolkit watches upstream regulatory feeds (GDPR, "
            "HIPAA, SOC 2, ISO 27001, etc.) and flags concepts that "
            "have shifted since your last review."
        ),
        "why": (
            "Compliance is usually retrospective: an annual audit, a "
            "scramble to gather evidence. Making it continuous — every "
            "ontology change asks 'does this still satisfy "
            "Section 5.4?' — moves the cost from spike to steady-state."
        ),
        "capabilities": [
            ("Regulation feed ingest (T3.4)",
             "Subscribed sources push updates; diffs are summarized "
             "and tagged with affected concepts."),
            ("Evidence trail",
             "Every approval, every CQ pass, every SHACL run is "
             "persisted with timestamps and signatures."),
            ("Coverage matrix",
             "Regulation clause × ontology concept grid — green = "
             "covered, amber = drifted, red = uncovered."),
            ("Audit export",
             "One-click PDF + JSON export with full provenance for "
             "external auditors."),
        ],
        "workflow": [
            ("Subscribe to regulations",
             "Pick from the catalog or paste a custom feed URL."),
            ("Review the coverage matrix",
             "Click an amber cell to see what drifted."),
            ("Action the gaps",
             "Each gap links back to the phase where it must be fixed "
             "(entities, rules, CQs)."),
            ("Export the audit pack",
             "Choose evidence scope; bundle drops to "
             "``output/compliance/``."),
        ],
        "tips": [
            "Run the compliance pass after every Evolution Review — "
            "it's where drift becomes visible.",
            "Custom regulation feeds must be ATOM or JSON Feed; PDF "
            "ingest is on the T3.4 roadmap.",
            "Audit exports include checksums of every artifact — "
            "auditors can independently verify nothing was tampered "
            "with after export.",
        ],
        "next": ("retrieve", "Vector Retrieval →"),
        "prev": ("evolve", "← Evolution Review"),
    },

    # ── Step 11 — Vector Retrieval ─────────────────────────────────────
    "retrieve": {
        "slug":     "retrieve",
        "step_num": "11",
        "title":    "Vector Retrieval",
        "tagline":  "Hybrid semantic + graph retrieval — the GraphRAG "
                    "frontend of the toolkit.",
        "what": (
            "Vector Retrieval indexes the ontology + materialized "
            "graph into a vector store and exposes a hybrid retriever "
            "that combines semantic similarity with graph-aware "
            "filtering. Use it as a drop-in retriever for any RAG "
            "stack — your LLM gets graph-grounded context instead of "
            "raw chunks."
        ),
        "why": (
            "Pure-vector retrieval blurs entity boundaries and "
            "hallucinates relations. Pure-graph retrieval is precise "
            "but brittle to phrasing. Hybrid retrieval gets both: "
            "precision from the graph, recall from embeddings."
        ),
        "capabilities": [
            ("Entity-aware chunking",
             "Each chunk carries its entity IRIs; retrieval can filter "
             "by class, by predicate, by sub-graph."),
            ("Multiple backends",
             "FAISS (local), Chroma, Qdrant, pgvector — switch via the "
             "Settings panel."),
            ("Re-ranking",
             "Cross-encoder re-ranker over the top-K candidates; "
             "graph-distance penalty included."),
            ("Drift surfacing",
             "When entity definitions change in Evolution Review, the "
             "affected vectors are flagged for re-embedding."),
        ],
        "workflow": [
            ("Pick a backend",
             "Default is FAISS in-process; production deployments use "
             "Qdrant or pgvector."),
            ("Build the index",
             "Reads the materialized graph from Phase 8; progress "
             "shows per-class counts."),
            ("Test a query",
             "Type a question; the wizard shows top-K results with "
             "their graph context."),
            ("Wire it up",
             "Copy the snippet for LangChain / LlamaIndex / direct "
             "Python — all three are emitted."),
        ],
        "tips": [
            "Re-embed after every Generate — a stale index is worse "
            "than no index.",
            "If query latency creeps up, profile the re-ranker first "
            "— it's almost always the bottleneck.",
            "For domains with many near-duplicate entities, lower the "
            "cosine threshold below the default 0.75 or you'll lose "
            "recall.",
        ],
        "next": None,
        "prev": ("comply", "← Compliance Dashboard"),
    },

}


def get_help(slug: str) -> dict | None:
    """Return the help page entry for ``slug``, or ``None`` if unknown."""
    return HELP_PAGES.get(slug)


def all_slugs() -> list[str]:
    """Ordered list of all phase slugs that have help pages."""
    return list(HELP_PAGES.keys())
