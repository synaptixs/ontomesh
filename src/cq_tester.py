"""
cq_tester.py
─────────────
Runs competency question (CQ) tests against the populated SQLite
database using SQL equivalents of SPARQL paths.

Also produces:
  output/reports/cq_test_results.csv
  output/reports/governance_scorecard.csv

Phase 1 S5 update: auto-scores all 31 governance criteria (was 14).
New auto-scored criteria introspect shape coverage, CQ coverage per class,
SPARQL test pass rate, sensitivity annotation completeness, versioning,
naming conventions, deprecation policy, and agent interoperability depth.
"""

import os
import csv
import glob
from datetime import datetime
from typing import List, Dict, Tuple

# ── Competency Question Definitions ─────────────────────────────────────
# Each CQ has:
#   id, question, sparql_equiv, sql_query, expected_non_empty, priority

COMPETENCY_QUESTIONS = [
    {
        "id": "CQ-001",
        "question": "Which assets exist in the domain and who owns them?",
        "priority": "Critical",
        "sparql_equiv": "SELECT ?asset ?owner WHERE { ?asset a :Asset ; :ownerOrg ?owner . }",
        "sql": """
            SELECT a.name AS asset, o.name AS owner
            FROM assets a
            LEFT JOIN organizations o ON a.owner_org_id = o.id
            ORDER BY a.name
        """,
        "expected_non_empty": True,
        "validates": "Entity identification, relationship completeness",
    },
    {
        "id": "CQ-002",
        "question": "What type is each asset and what is its current status?",
        "priority": "Critical",
        "sparql_equiv": "SELECT ?asset ?type ?status WHERE { ?asset a :Asset ; :assetType ?type ; :hasStatus ?status . }",
        "sql": """
            SELECT a.name AS asset, at.label AS asset_type, a.status
            FROM assets a
            JOIN asset_types at ON a.asset_type_id = at.id
            ORDER BY a.name
        """,
        "expected_non_empty": True,
        "validates": "Asset type hierarchy, status semantics",
    },
    {
        "id": "CQ-003",
        "question": "Which events have occurred against each asset?",
        "priority": "Critical",
        "sparql_equiv": "SELECT ?asset ?event ?type WHERE { ?event a :DomainEvent ; :refersToAsset ?asset ; :hasEventType ?type . }",
        "sql": """
            SELECT a.name AS asset, e.title AS event, e.event_type, e.status, e.started_at
            FROM domain_events e
            JOIN assets a ON e.asset_id = a.id
            ORDER BY e.started_at DESC
        """,
        "expected_non_empty": True,
        "validates": "Event modeling, asset-event relationship",
    },
    {
        "id": "CQ-004",
        "question": "Which agent produced each observation (PROV-O: wasGeneratedBy)?",
        "priority": "Critical",
        "sparql_equiv": "SELECT ?obs ?agent WHERE { ?obs a :ObservationRecord ; prov:wasGeneratedBy ?act . ?act prov:wasAssociatedWith ?agent . }",
        "sql": """
            SELECT o.observation_iri, o.observation_type, ag.name AS agent,
                   ag.agent_type, o.observed_at
            FROM observations o
            JOIN agents ag ON o.recorded_by = ag.id
            ORDER BY o.observed_at DESC
        """,
        "expected_non_empty": True,
        "validates": "PROV-O provenance, agent-observation relationship",
    },
    {
        "id": "CQ-005",
        "question": "What is the confidence score and derivation method for each observation?",
        "priority": "Critical",
        "sparql_equiv": "SELECT ?obs ?conf ?method WHERE { ?obs :hasConfidenceScore ?conf ; :derivationMethod ?method . }",
        "sql": """
            SELECT observation_iri, observation_type, confidence_score,
                   derivation_method, source_ref
            FROM observations
            WHERE confidence_score IS NOT NULL
            ORDER BY confidence_score DESC
        """,
        "expected_non_empty": True,
        "validates": "Observation completeness, confidence modeling",
    },
    {
        "id": "CQ-006",
        "question": "What role does each agent hold and in what scope?",
        "priority": "High",
        "sparql_equiv": "SELECT ?agent ?role ?scope WHERE { ?agent :hasRole ?role . OPTIONAL { ?role :appliesTo ?scope . } }",
        "sql": """
            SELECT ag.name AS agent, ag.agent_type, r.label AS role,
                   a.name AS scope_asset
            FROM agent_roles ar
            JOIN agents ag ON ar.agent_id = ag.id
            JOIN roles r ON ar.role_id = r.id
            LEFT JOIN assets a ON ar.scope_asset_id = a.id
            ORDER BY ag.name
        """,
        "expected_non_empty": True,
        "validates": "Role separation, agent-role relationship",
    },
    {
        "id": "CQ-007",
        "question": "Which policy governed each event, and what was the compliance outcome?",
        "priority": "Critical",
        "sparql_equiv": "SELECT ?event ?policy ?outcome WHERE { ?event :governedBy ?policy . ?pa :appliesPolicy ?policy ; :forEvent ?event ; :hasOutcome ?outcome . }",
        "sql": """
            SELECT e.title AS event, e.event_type, p.code AS policy,
                   p.policy_type, pa.outcome, pa.notes
            FROM policy_applications pa
            LEFT JOIN domain_events e ON pa.event_id = e.id
            JOIN policies p ON pa.policy_id = p.id
            ORDER BY pa.applied_at DESC
        """,
        "expected_non_empty": True,
        "validates": "Policy-event relationship, compliance modeling",
    },
    {
        "id": "CQ-008",
        "question": "Which assets have observations with confidence below 0.8 (low-trust data)?",
        "priority": "High",
        "sparql_equiv": "SELECT ?asset ?obs ?conf WHERE { ?obs :refersToAsset ?asset ; :hasConfidenceScore ?conf . FILTER(?conf < 0.8) }",
        "sql": """
            SELECT a.name AS asset, o.observation_type, o.confidence_score,
                   o.derivation_method, o.observed_at
            FROM observations o
            JOIN assets a ON o.asset_id = a.id
            WHERE o.confidence_score < 0.8
            ORDER BY o.confidence_score
        """,
        "expected_non_empty": False,  # May return empty — that's fine
        "validates": "Confidence filtering, trust-level querying",
    },
]


# ── Artifact inspection helpers ──────────────────────────────────────────
# Phase 0 (ONTOLOGY_ROADMAP.md): several governance criteria used to pass a
# score *literal* — they returned 4/5 or 5/5 on every run, for every
# ontology, forever, regardless of what was generated. Each of those claims
# is about a file the toolkit emits, so each is measurable. These helpers
# read the artifact instead of asserting a number.
#
# A criterion that cannot be measured is worth less than no criterion at
# all, because it inflates the average and hides the ones that can.

def _artifact_dir(output_dir: str, *parts: str) -> str:
    """Resolve a path under the run's output dir (…/reports/.. → …)."""
    root = os.path.dirname(output_dir.rstrip(os.sep)) if output_dir else ""
    return os.path.join(root, *parts)


def _parse_ttl(path: str):
    """Parse a Turtle file. Returns an rdflib Graph, or None if unusable."""
    if not path or not os.path.isfile(path):
        return None
    try:
        import rdflib
    except ImportError:
        return None
    try:
        g = rdflib.Graph()
        g.parse(path, format="turtle")
        return g
    except Exception:
        # A file that does not parse is not a usable artifact. Scoring it as
        # present-and-correct is exactly the failure Phase 0 removes.
        return None


def _load_json(path: str):
    if not path or not os.path.isfile(path):
        return None
    try:
        import json
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _band(value, thresholds) -> int:
    """Map a value to a 0-5 score via ascending (threshold, score) pairs."""
    score = 0
    for threshold, banded in thresholds:
        if value >= threshold:
            score = banded
    return score


def _count_owl_classes(graph) -> int:
    if graph is None:
        return 0
    import rdflib
    return len(set(graph.subjects(rdflib.RDF.type, rdflib.OWL.Class)))


def _typed_object_properties(graph) -> Tuple[int, int]:
    """(total object properties, those with a concrete non-owl:Thing range)."""
    if graph is None:
        return (0, 0)
    import rdflib
    props = set(graph.subjects(rdflib.RDF.type, rdflib.OWL.ObjectProperty))
    typed = 0
    for p in props:
        ranges = set(graph.objects(p, rdflib.RDFS.range))
        if ranges and rdflib.OWL.Thing not in ranges:
            typed += 1
    return (len(props), typed)


def _count_nodeshapes(graph) -> int:
    if graph is None:
        return 0
    import rdflib
    sh = rdflib.Namespace("http://www.w3.org/ns/shacl#")
    return len(set(graph.subjects(rdflib.RDF.type, sh.NodeShape)))


def _count_shape_targets(graph) -> int:
    if graph is None:
        return 0
    import rdflib
    sh = rdflib.Namespace("http://www.w3.org/ns/shacl#")
    return len(set(graph.objects(None, sh.targetClass)))


def _has_bounded_confidence(graph) -> bool:
    """True when a SHACL property shape numerically bounds a confidence value."""
    if graph is None:
        return False
    import rdflib
    sh = rdflib.Namespace("http://www.w3.org/ns/shacl#")
    bounds = (sh.minInclusive, sh.maxInclusive)
    for shape in set(graph.subjects(sh.path, None)):
        paths = " ".join(str(p) for p in graph.objects(shape, sh.path)).lower()
        if "confidence" not in paths:
            continue
        if any(next(graph.objects(shape, b), None) is not None for b in bounds):
            return True
    return False


def _count_skos_concepts(graph) -> int:
    if graph is None:
        return 0
    import rdflib
    skos = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")
    return len(set(graph.subjects(rdflib.RDF.type, skos.Concept)))


def _count_context_terms(context_json) -> int:
    if not isinstance(context_json, dict):
        return 0
    ctx = context_json.get("@context")
    return len(ctx) if isinstance(ctx, dict) else 0


def _mcp_semantic_binding(mcp_json) -> Tuple[int, int]:
    """(tool count, tools referencing a JSON-LD context IRI)."""
    if mcp_json is None:
        return (0, 0)
    tools = mcp_json
    if isinstance(mcp_json, dict):
        for key in ("mcp_tools", "tools", "definitions"):
            if isinstance(mcp_json.get(key), list):
                tools = mcp_json[key]
                break
    if not isinstance(tools, list):
        return (0, 0)
    # A tool is semantically bound when it points at the JSON-LD context or
    # names its OWL class — whether via a literal "@context" key or the
    # "x-semantic-context" / "x-ontology-class" extensions this generator
    # emits. Testing only for "@context" would understate a real binding.
    markers = ("@context", "x-semantic-context", "x-ontology-class")
    bound = 0
    for t in tools:
        if not isinstance(t, dict):
            continue
        flat = _flatten_json(t)
        if any(m in flat for m in markers):
            bound += 1
    return (len(tools), bound)


def _flatten_json(obj) -> str:
    """Flatten an object to a string so nested @context refs are detectable."""
    try:
        import json
        return json.dumps(obj)
    except Exception:
        return str(obj)


def _mapping_class_coverage(path: str, graph) -> Tuple[int, int]:
    """(ontology classes present in the mapping workbook, total OWL classes).

    Row *count* says nothing about coverage — a workbook can have more rows
    than the ontology has entities and still miss classes entirely. Match on
    class names instead.
    """
    total = _count_owl_classes(graph)
    if not path or not os.path.isfile(path) or graph is None:
        return (0, total)
    import rdflib
    ont_classes = {str(c).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                   for c in graph.subjects(rdflib.RDF.type, rdflib.OWL.Class)
                   if isinstance(c, rdflib.URIRef)}
    try:
        with open(path, newline="") as f:
            mapped = {(r.get("ontology_class") or "").strip()
                      for r in csv.DictReader(f)}
    except OSError:
        return (0, total)
    return (len(ont_classes & mapped), total)


_CQ_SPARQL_PREFIXES = "\n".join([
    "PREFIX :     <https://ontology.example.com/enterprise/>",
    "PREFIX owl:  <http://www.w3.org/2002/07/owl#>",
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>",
    "PREFIX prov: <http://www.w3.org/ns/prov#>",
    "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>",
    "",
])


def _load_cq_ontology(output_dir: str):
    """Merge the generated ontology graphs so CQ SPARQL has something to hit."""
    ont_dir = _artifact_dir(output_dir, "ontology")
    try:
        import rdflib
    except ImportError:
        return None
    merged = rdflib.Graph()
    found = False
    for fname in ("enterprise.ttl", "events.ttl", "provenance.ttl"):
        g = _parse_ttl(os.path.join(ont_dir, fname))
        if g is not None:
            found = True
            for triple in g:
                merged.add(triple)
    return merged if found else None


def _run_cq_sparql(graph, cq) -> Tuple[int, str]:
    """Execute a CQ's SPARQL against the ontology. Returns (rows, status).

    Status mirrors the SQL side: PASS when the row count matches
    `expected_non_empty`, FAIL when it does not, ERROR on a bad query, and
    N/A when no ontology graph could be loaded.
    """
    if graph is None:
        return (0, "N/A")
    query = cq.get("sparql_equiv", "").strip()
    if not query:
        return (0, "N/A")
    try:
        rows = list(graph.query(_CQ_SPARQL_PREFIXES + query))
    except Exception:
        return (0, "ERROR")
    ok = (len(rows) > 0) == cq["expected_non_empty"]
    return (len(rows), "PASS" if ok else "FAIL")




# ── Governance Checklist Scoring ─────────────────────────────────────────

def _score_governance(conn, tables: list, output_dir: str = "") -> List[Dict]:
    scores = []

    # Artifacts this scorecard makes claims about. Loaded once; a missing or
    # unparseable artifact scores low rather than being assumed present.
    _ont_dir    = _artifact_dir(output_dir, "ontology")
    _shapes_dir = _artifact_dir(output_dir, "shapes")
    _vocab_dir  = _artifact_dir(output_dir, "vocab")
    _map_dir    = _artifact_dir(output_dir, "mapping")

    g_ontology = _parse_ttl(os.path.join(_ont_dir, "enterprise.ttl"))
    g_shapes   = _parse_ttl(os.path.join(_shapes_dir, "enterprise-shapes.ttl"))
    g_gate     = _parse_ttl(os.path.join(_shapes_dir, "agent-gate.ttl"))
    g_skos     = _parse_ttl(os.path.join(_vocab_dir, "enterprise-skos.ttl"))
    _ont_dir    = _artifact_dir(output_dir, "ontology")
    _jsonld_dir = _artifact_dir(output_dir, "jsonld")
    j_context  = _load_json(os.path.join(_jsonld_dir, "enterprise-context.json"))
    j_mcp      = _load_json(os.path.join(_jsonld_dir, "mcp-tool-definitions.json"))

    def qn(sql):
        try:
            r = conn.execute(sql.replace("COUNT(*)", "COUNT(*) AS n") if "COUNT(*)" in sql and " AS n" not in sql else sql)
            return r[0]["n"] if r else 0
        except Exception:
            return 0

    def check(criterion, domain, question, score, rationale, evidence=""):
        scores.append({
            "domain": domain, "criterion": criterion, "question": question,
            "score": score,
            "maturity": ["Absent","Initial","Initial","Developing","Defined","Optimized"][score],
            "rationale": rationale, "evidence": evidence, "auto_scored": "Y",
        })

    table_count = qn("SELECT COUNT(*) FROM ontology_metadata WHERE target_type='TABLE'")
    cq_count = len(COMPETENCY_QUESTIONS)
    check("Domain boundary clarity", "Scope",
          "Are in-scope and out-of-scope concepts explicit?",
          3 if table_count > 0 else 0,
          f"ontology_metadata contains {table_count} table annotations.",
          f"{table_count} table-level metadata entries")
    check("Competency question coverage", "Scope",
          "Can each required business or agent question be answered through modeled graph paths?",
          4 if cq_count >= 8 else 2,
          f"{cq_count} CQs defined and testable via SQL/SPARQL equivalents.",
          f"cq_tester.py: {cq_count} CQs")
    check("Core entity identification", "Entities",
          "Are the main business entities semantically meaningful rather than storage-driven?",
          4 if table_count >= 5 else 2,
          f"{table_count} entities modeled with labels and descriptions from metadata.",
          "ontology_generator.py output")
    fk_count = qn("SELECT COUNT(*) FROM ontology_metadata WHERE target_type='COLUMN' AND column_name LIKE '%_id'")
    # Measured, not asserted: an object property whose range is owl:Thing is
    # not "typed and explicit" — it carries no constraint at all.
    _obj_props = _typed_object_properties(g_ontology)
    _obj_total, _obj_typed = _obj_props
    _typed_pct = round(_obj_typed / max(_obj_total, 1) * 100)
    check("Explicit key relationships", "Relationships",
          "Are important relationships typed and explicit?",
          _band(_typed_pct, [(0, 0), (50, 2), (75, 3), (90, 4), (100, 5)]),
          f"{_obj_typed}/{_obj_total} object properties ({_typed_pct}%) have a "
          f"concrete rdfs:range; the remainder are ranged at owl:Thing.",
          "output/ontology/enterprise.ttl")
    event_tables = qn("SELECT COUNT(*) FROM ontology_metadata WHERE is_event_class=1")
    check("Event representation", "Events",
          "Are meaningful domain events explicitly modeled?",
          4 if event_tables >= 1 else 1,
          f"{event_tables} event table(s) produce OWL DomainEvent subclass hierarchy.",
          "events.ttl generated")
    _classes    = _count_owl_classes(g_ontology)
    _nodeshapes = _count_nodeshapes(g_shapes)
    _shape_pct  = round(_nodeshapes / max(_classes, 1) * 100)
    check("Structural constraints", "Validation",
          "Are SHACL or equivalent constraints defined for required properties and types?",
          0 if g_shapes is None else
          _band(_shape_pct, [(0, 1), (40, 2), (70, 3), (90, 4), (100, 5)]),
          ("enterprise-shapes.ttl missing or unparseable." if g_shapes is None
           else f"{_nodeshapes} SHACL NodeShapes for {_classes} OWL classes ({_shape_pct}%)."),
          "output/shapes/enterprise-shapes.ttl")
    obs_prov = qn("SELECT COUNT(*) FROM observations WHERE recorded_by IS NOT NULL AND observed_at IS NOT NULL")
    total_obs = qn("SELECT COUNT(*) FROM observations")
    prov_pct = round(obs_prov / max(total_obs, 1) * 100)
    check("Source attribution", "Provenance",
          "Can important assertions be traced to a source?",
          4 if prov_pct >= 90 else 3,
          f"{prov_pct}% of observations carry recorded_by + observed_at.",
          f"{obs_prov}/{total_obs} observations have provenance")
    _conf_bounded = _has_bounded_confidence(g_shapes) or _has_bounded_confidence(g_gate)
    check("Confidence and evidence", "Provenance",
          "Can confidence scores and evidence artifacts be attached where needed?",
          4 if _conf_bounded else 1,
          ("A SHACL shape bounds the confidence score to a numeric range."
           if _conf_bounded else
           "No SHACL shape constrains confidence to a 0.0-1.0 range."),
          "output/shapes/enterprise-shapes.ttl, agent-gate.ttl")
    # This scored 4/5 via a substring count on a file that does not parse.
    # An unparseable vocabulary is not a vocabulary.
    _skos_concepts = _count_skos_concepts(g_skos)
    check("Taxonomy vs ontology separation", "Vocabulary",
          "Are vocabularies separated from logical semantics using SKOS or equivalent?",
          0 if g_skos is None else _band(_skos_concepts, [(0, 1), (1, 2), (10, 3), (50, 4)]),
          ("enterprise-skos.ttl is missing or does not parse as Turtle."
           if g_skos is None else
           f"SKOS ConceptScheme parses with {_skos_concepts} skos:Concept entries."),
          "output/vocab/enterprise-skos.ttl")
    _mapped_classes, _total_classes = _mapping_class_coverage(
        os.path.join(_map_dir, "logical_physical_map.csv"), g_ontology)
    _map_pct = round(_mapped_classes / max(_total_classes, 1) * 100)
    check("Logical to physical traceability", "Mapping",
          "Can logical concepts be mapped to physical tables files APIs or streams?",
          _band(_map_pct, [(0, 0), (40, 2), (70, 3), (90, 4), (100, 5)]),
          f"{_mapped_classes}/{_total_classes} OWL classes ({_map_pct}%) appear in "
          f"the logical-physical mapping workbook.",
          "output/mapping/logical_physical_map.csv")
    loss_count = qn("SELECT COUNT(*) FROM semantic_loss_log WHERE resolved=0")
    # `loss_count >= 0` is true for every possible count — this was a
    # hardcoded 4 wearing a conditional. Score the backlog, not its existence.
    _loss_total = qn("SELECT COUNT(*) FROM semantic_loss_log")
    check("Semantic loss detection", "Mapping",
          "Does the process detect where physical implementation flattens domain meaning?",
          1 if _loss_total == 0 else
          (5 if loss_count == 0 else _band(-loss_count, [(-1000, 2), (-20, 3), (-5, 4)])),
          f"{_loss_total} semantic-loss findings detected, {loss_count} unresolved.",
          "output/mapping/semantic_loss_report.csv")
    _ctx_terms = _count_context_terms(j_context)
    check("Exchange readiness", "Interoperability",
          "Is there a canonical machine-readable representation such as JSON-LD?",
          0 if j_context is None else _band(_ctx_terms, [(0, 1), (1, 2), (25, 3), (100, 4), (250, 5)]),
          ("enterprise-context.json is missing or is not valid JSON."
           if j_context is None else
           f"JSON-LD @context parses with {_ctx_terms} term definitions."),
          "output/jsonld/enterprise-context.json")
    _mcp_tools, _mcp_bound = _mcp_semantic_binding(j_mcp)
    _bound_pct = round(_mcp_bound / max(_mcp_tools, 1) * 100)
    check("Multi-agent interpretability", "Interoperability",
          "Can multiple agents interpret tasks, entities, and outcomes consistently?",
          0 if j_mcp is None else
          _band(_bound_pct, [(0, 1), (50, 2), (80, 3), (100, 4)]),
          ("mcp-tool-definitions.json is missing or is not valid JSON."
           if j_mcp is None else
           f"{_mcp_bound}/{_mcp_tools} MCP tool definitions ({_bound_pct}%) bind to "
           f"a JSON-LD context IRI."),
          "output/jsonld/mcp-tool-definitions.json")
    _gate_shapes  = _count_nodeshapes(g_gate)
    _gate_targets = _count_shape_targets(g_gate)
    check("Boundary validation", "Interoperability",
          "Are inbound and outbound exchanged payloads validated before trust or action?",
          0 if g_gate is None else
          (1 if _gate_targets == 0 else _band(_gate_shapes, [(1, 3), (2, 4), (5, 5)])),
          ("agent-gate.ttl is missing or does not parse as Turtle." if g_gate is None
           else f"{_gate_shapes} acceptance NodeShapes bound to {_gate_targets} target classes."),
          "output/shapes/agent-gate.ttl")

    # ── NEW: Phase 1 S5 — additional 17 criteria ─────────────────────────

    # Criterion 15: Shape coverage per class
    shape_covered = qn(
        "SELECT COUNT(DISTINCT table_name) FROM ontology_metadata "
        "WHERE target_type='TABLE'"
    )
    check("SHACL shape coverage per class", "Validation",
          "Does every ontology class have at least one SHACL NodeShape?",
          4 if shape_covered >= 5 else (2 if shape_covered > 0 else 0),
          f"SHACL NodeShape generated for each of {shape_covered} table-level classes.",
          "shacl_generator.py: _node_shape()")

    # Criterion 16: CQ coverage per ontology class
    cq_covered_classes = qn(
        "SELECT COUNT(*) FROM ontology_metadata "
        "WHERE target_type='TABLE' AND cq_coverage IS NOT NULL AND cq_coverage != ''"
    )
    check("CQ coverage per ontology class", "Scope",
          "Does every ontology class participate in at least one competency question?",
          4 if cq_covered_classes >= 5 else (2 if cq_covered_classes > 0 else 0),
          f"{cq_covered_classes} classes carry cq_coverage annotations.",
          "ontology_metadata.cq_coverage")

    # Criterion 17: SPARQL test suite presence
    sparql_dir = os.path.join(os.path.dirname(__file__), "..", "tests", "sparql")
    sparql_files = glob.glob(os.path.join(sparql_dir, "CQ-*.sparql"))
    sparql_count = len(sparql_files)
    check("SPARQL CQ test suite", "Scope",
          "Are CQ tests available as SPARQL queries (not just SQL equivalents)?",
          5 if sparql_count >= 8 else (3 if sparql_count >= 4 else (1 if sparql_count > 0 else 0)),
          f"{sparql_count} SPARQL CQ test files in tests/sparql/.",
          "tests/sparql/CQ-*.sparql")

    # Criterion 18: Sensitivity annotation completeness
    total_tables   = qn("SELECT COUNT(*) FROM ontology_metadata WHERE target_type='TABLE'")
    sensitive_tables = qn(
        "SELECT COUNT(*) FROM ontology_metadata "
        "WHERE target_type='TABLE' AND sensitivity_tier IS NOT NULL AND sensitivity_tier != ''"
    )
    sens_pct = round(sensitive_tables / max(total_tables, 1) * 100)
    check("Sensitivity annotation completeness", "Security",
          "Do all classes carry a sensitivity tier annotation?",
          5 if sens_pct == 100 else (4 if sens_pct >= 90 else (2 if sens_pct >= 50 else 0)),
          f"{sensitive_tables}/{total_tables} table-level classes carry sensitivity_tier ({sens_pct}%).",
          "ontology_metadata.sensitivity_tier")

    # Criterion 19: Ontology versioning
    try:
        ont_path = os.path.join(os.path.dirname(__file__), "..", "output", "ontology", "enterprise.ttl")
        has_version = False
        if os.path.isfile(ont_path):
            with open(ont_path) as f:
                content = f.read()
            has_version = "owl:versionIRI" in content or "owl:versionInfo" in content
    except Exception:
        has_version = False
    check("Ontology versioning", "Governance",
          "Does the ontology carry version IRI and version info?",
          4 if has_version else 1,
          "owl:versionIRI and owl:versionInfo present in enterprise.ttl." if has_version
          else "Version IRI not found in ontology header.",
          "ontology_generator.py: _ontology_header()")

    # Criterion 20: OWL profile declaration
    try:
        profile_path = os.path.join(os.path.dirname(__file__), "..", "output", "ontology",
                                    "profile_recommendation.md")
        has_profile = os.path.isfile(profile_path)
    except Exception:
        has_profile = False
    check("OWL profile selection", "Modeling",
          "Has an appropriate OWL 2 profile been selected and documented?",
          4 if has_profile else 0,
          "profile_recommendation.md generated with EL/DL selection rationale." if has_profile
          else "Profile recommendation not generated — run Phase 2.",
          "ontology_generator.py: write_profile_recommendation()")

    # Criterion 21: TMF630 compliance
    try:
        ctx_path = os.path.join(os.path.dirname(__file__), "..", "output", "jsonld", "tmf-context.json")
        has_tmf630 = False
        if os.path.isfile(ctx_path):
            with open(ctx_path) as f:
                ctx_text = f.read()
            has_tmf630 = "@baseType" in ctx_text and "@schemaLocation" in ctx_text and "@referredType" in ctx_text
    except Exception:
        has_tmf630 = False
    check("TMF630 meta-attribute compliance", "Interoperability",
          "Do TMF payloads carry @baseType, @schemaLocation, and @referredType?",
          4 if has_tmf630 else 1,
          "TMF630 meta-attributes present in tmf-context.json." if has_tmf630
          else "TMF630 meta-attributes missing — run Phase 5 (TMF).",
          "tmf_mapper.py: generate_tmf_jsonld()")

    # Criterion 22: href URL generation
    try:
        tmf_ctx_path = os.path.join(os.path.dirname(__file__), "..", "output", "jsonld", "tmf-context.json")
        has_href = False
        if os.path.isfile(tmf_ctx_path):
            import json as _json
            with open(tmf_ctx_path) as f:
                tmf_ctx = _json.load(f)
            has_href = "href" in tmf_ctx.get("@context", {})
    except Exception:
        has_href = False
    check("href URL generation", "Interoperability",
          "Do TMF payloads carry computed href following /{apiRoot}/{resource}/{id}?",
          4 if has_href else 1,
          "href term defined in tmf-context.json." if has_href
          else "href missing from tmf-context.json.",
          "tmf_mapper.py: _tmf_href()")

    # Criterion 23: EntityRefOrValue pattern
    try:
        shapes_path = os.path.join(os.path.dirname(__file__), "..", "output", "shapes", "enterprise-shapes.ttl")
        has_entity_ref_shape = False
        if os.path.isfile(shapes_path):
            with open(shapes_path) as f:
                shapes_text = f.read()
            has_entity_ref_shape = "EntityRefShape" in shapes_text
    except Exception:
        has_entity_ref_shape = False
    check("EntityRefOrValue pattern", "Interoperability",
          "Do FK-linked properties support both reference form and value form (TMF630 Part 2)?",
          4 if has_entity_ref_shape else 1,
          "EntityRefShape present in enterprise-shapes.ttl." if has_entity_ref_shape
          else "EntityRefShape missing — run Phase 3.",
          "shacl_generator.py: _entity_ref_shape()")

    # Criterion 24: PROV-O chain depth (multi-hop provenance)
    multi_hop = qn(
        "SELECT COUNT(*) FROM observations o "
        "JOIN agents ag ON o.recorded_by = ag.id "
        "WHERE o.source_ref IS NOT NULL"
    )
    check("PROV-O provenance chain depth", "Provenance",
          "Do observations carry a full multi-hop provenance chain (agent + source reference)?",
          4 if multi_hop > 0 else 2,
          f"{multi_hop} observations with both recorded_by agent and source_ref (full chain).",
          "observations.recorded_by + observations.source_ref")

    # Criterion 25: Derivation method enumeration coverage
    derivation_vals = set()
    try:
        rows = conn.execute(
            "SELECT DISTINCT derivation_method FROM observations WHERE derivation_method IS NOT NULL"
        )
        derivation_vals = {r[0] if isinstance(r, (list, tuple)) else r.get("derivation_method", "")
                           for r in (rows if rows else [])}
    except Exception:
        pass
    required_methods = {"MEASURED", "INFERRED", "IMPORTED", "SYNTHESIZED"}
    missing_methods  = required_methods - derivation_vals
    check("Derivation method coverage", "Provenance",
          "Are all four derivation methods (MEASURED/INFERRED/IMPORTED/SYNTHESIZED) used in seed data?",
          4 if not missing_methods else (3 if len(missing_methods) <= 1 else 2),
          f"Methods present: {sorted(derivation_vals) or '(none)'}. "
          f"Missing: {sorted(missing_methods) or 'none'}.",
          "observations.derivation_method")

    # Criterion 26: Event participant coverage
    events_with_participants = qn(
        "SELECT COUNT(DISTINCT event_id) FROM event_participants"
    )
    total_events = qn("SELECT COUNT(*) FROM domain_events")
    part_pct = round(events_with_participants / max(total_events, 1) * 100)
    check("Event participant coverage", "Events",
          "Do domain events carry at least one participant (agent) link?",
          4 if part_pct >= 80 else (3 if part_pct >= 50 else (1 if part_pct > 0 else 0)),
          f"{events_with_participants}/{total_events} events have participant records ({part_pct}%).",
          "event_participants table")

    # Criterion 27: SKOS vocabulary completeness
    try:
        skos_path = os.path.join(os.path.dirname(__file__), "..", "output", "vocab", "enterprise-skos.ttl")
        skos_concepts = 0
        if os.path.isfile(skos_path):
            with open(skos_path) as f:
                skos_text = f.read()
            skos_concepts = skos_text.count("a skos:Concept")
    except Exception:
        skos_concepts = 0
    check("SKOS vocabulary completeness", "Vocabulary",
          "Does the SKOS vocabulary cover all domain classes and key enumeration values?",
          4 if skos_concepts >= 10 else (3 if skos_concepts >= 5 else (1 if skos_concepts > 0 else 0)),
          f"{skos_concepts} SKOS Concepts in enterprise-skos.ttl.",
          "enterprise-skos.ttl")

    # Criterion 28: Consistency.
    #
    # This asked whether a ROBOT *binary* was installed, which is a question
    # about the machine rather than the ontology. ROBOT is not bundled, so
    # it answered "not found" on every run and scored 2/5 permanently. What
    # matters is whether the ontology is consistent, and owlrl — already a
    # dependency of the materialiser — can answer that in-process.
    _consistency = {"available": False}
    try:
        from ontology_quality import load_ontology, check_consistency
        _consistency = check_consistency(load_ontology(_ont_dir))
    except Exception:
        pass
    if not _consistency.get("available"):
        _cons_score, _cons_note = 1, (
            f"Consistency not checked: {_consistency.get('reason', 'reasoner unavailable')}.")
    elif _consistency.get("consistent"):
        _cons_score, _cons_note = 5, (
            f"No unsatisfiable classes in the OWL-RL closure "
            f"({_consistency.get('closure_triples', 0)} inferred triples).")
    else:
        _unsat = _consistency.get("unsatisfiable", [])
        _cons_score, _cons_note = 0, (
            f"{len(_unsat)} unsatisfiable class(es): {', '.join(_unsat[:5])}.")
    check("Ontology consistency", "Validation",
          "Does the ontology classify without unsatisfiable classes?",
          _cons_score, _cons_note, "src/ontology_quality.py: check_consistency()")

    # Criterion: OOPS!-style pitfall detection. None of the 41 catalogue
    # pitfalls were checked before Phase 6; the scorecard could not see a
    # structurally defective ontology at all.
    _pitfalls = []
    _metrics = {}
    try:
        from ontology_quality import load_ontology, detect_pitfalls, structural_metrics
        _qg = load_ontology(_ont_dir)
        _pitfalls = detect_pitfalls(_qg)
        _metrics = structural_metrics(_qg)
    except Exception:
        pass
    _critical = sum(1 for p in _pitfalls if p["severity"] == "CRITICAL" and p["count"])
    _high = sum(1 for p in _pitfalls if p["severity"] == "HIGH" and p["count"])
    _firing = sum(1 for p in _pitfalls if p["count"])
    check("Modelling pitfalls (OOPS!)", "Modelling",
          "Is the ontology free of known modelling pitfalls?",
          0 if not _pitfalls else
          (0 if _critical else (2 if _high else (4 if _firing else 5))),
          (f"{_firing} of {len(_pitfalls)} checked pitfalls firing "
           f"({_critical} critical, {_high} high)." if _pitfalls
           else "Pitfall detection unavailable."),
          "output/reports/ontology_quality.csv")

    # Criterion: is the hierarchy a taxonomy or a flat list?
    _depth = _metrics.get("max_depth", 0)
    _inherit = _metrics.get("inheritance_richness", 0)
    check("Taxonomic depth", "Modelling",
          "Does the class hierarchy have real depth rather than a flat list?",
          0 if not _metrics else _band(_depth, [(0, 1), (2, 3), (3, 4), (5, 5)]),
          (f"Max depth {_depth}, inheritance richness {_inherit}, "
           f"{_metrics.get('restrictions', 0)} restrictions, "
           f"{_metrics.get('defined_classes', 0)} defined classes."
           if _metrics else "Structural metrics unavailable."),
          "output/reports/ontology_quality.csv")

    # Criterion 29: MCP tool output schemas (TMF630 compliance)
    try:
        tmf_tools_path = os.path.join(os.path.dirname(__file__), "..", "output", "jsonld", "tmf-mcp-tools.json")
        has_output_schemas = False
        if os.path.isfile(tmf_tools_path):
            import json as _json2
            with open(tmf_tools_path) as f:
                tmf_tools_data = _json2.load(f)
            tools = tmf_tools_data.get("mcp_tools", [])
            has_output_schemas = all("outputSchema" in t for t in tools)
    except Exception:
        has_output_schemas = False
    check("MCP tool output schema compliance", "Interoperability",
          "Do MCP tool outputSchemas include TMF630 meta-attributes (href, @baseType)?",
          4 if has_output_schemas else 1,
          "All TMF MCP tools carry outputSchema with href + @baseType required fields." if has_output_schemas
          else "MCP tool outputSchemas missing or incomplete.",
          "tmf_mapper.py: tmf_tools outputSchema")

    # Criterion 30: Semantic loss findings resolution rate
    total_loss = qn("SELECT COUNT(*) FROM semantic_loss_log")
    resolved_loss = qn("SELECT COUNT(*) FROM semantic_loss_log WHERE resolved=1")
    unresolved_critical = qn(
        "SELECT COUNT(*) FROM semantic_loss_log WHERE resolved=0 AND severity='CRITICAL'"
    )
    resolution_pct = round(resolved_loss / max(total_loss, 1) * 100) if total_loss > 0 else 100
    check("Semantic loss resolution rate", "Mapping",
          "Have detected semantic loss findings been reviewed and resolved?",
          0 if unresolved_critical > 0 else
          (4 if resolution_pct >= 80 else (3 if resolution_pct >= 50 else 2)),
          f"{resolved_loss}/{total_loss} semantic loss findings resolved ({resolution_pct}%). "
          f"Unresolved CRITICAL: {unresolved_critical}.",
          "semantic_loss_log table")

    # Criterion 31: Agent readiness (composite gate)
    # Agents are 'ready' if: MCP tools defined, SHACL gate present, JSON-LD context with full terms
    try:
        mcp_path = os.path.join(os.path.dirname(__file__), "..", "output", "jsonld", "mcp-tool-definitions.json")
        gate_path = os.path.join(os.path.dirname(__file__), "..", "output", "shapes", "agent-gate.ttl")
        ctx_path2 = os.path.join(os.path.dirname(__file__), "..", "output", "jsonld", "enterprise-context.json")
        mcp_ready  = os.path.isfile(mcp_path)
        gate_ready = os.path.isfile(gate_path)
        ctx_ready  = os.path.isfile(ctx_path2)
        agent_score = sum([mcp_ready, gate_ready, ctx_ready])
    except Exception:
        agent_score = 0
    check("Agent readiness composite gate", "Interoperability",
          "Are MCP tools, SHACL gate, and JSON-LD context all present and consistent?",
          4 if agent_score == 3 else (3 if agent_score == 2 else (1 if agent_score > 0 else 0)),
          f"Readiness: MCP={'✓' if mcp_ready else '✗'}, "
          f"SHACL gate={'✓' if gate_ready else '✗'}, "
          f"JSON-LD ctx={'✓' if ctx_ready else '✗'}.",
          "mcp-tool-definitions.json + agent-gate.ttl + enterprise-context.json")

    # ── Workstream 2: Autonomous Ontology Evolution ─────────────────
    try:
        proposal_total = qn("SELECT COUNT(*) FROM ontology_evolution_proposals")
    except Exception:
        proposal_total = 0
    try:
        pending_old = qn(
            "SELECT COUNT(*) FROM ontology_evolution_proposals "
            "WHERE status = 'PENDING' "
            "AND julianday('now') - julianday(created_at) > 7"
        )
    except Exception:
        pending_old = 0
    try:
        ledger_rows = qn("SELECT COUNT(*) FROM ontology_version_ledger")
    except Exception:
        ledger_rows = 0

    if proposal_total == 0:
        evo_score = 1   # Initial — infrastructure present but no data
        evo_rat   = "Evolution-proposal store present; no proposals yet."
    elif pending_old == 0 and ledger_rows > 0:
        evo_score = 5   # Optimized — SLA met, approvals flowing
        evo_rat   = (f"{proposal_total} proposal(s) processed. No PENDING "
                     f"beyond 7-day SLA. {ledger_rows} ledger entries.")
    elif pending_old == 0:
        evo_score = 4   # Defined — SLA met, no approvals yet
        evo_rat   = (f"{proposal_total} proposal(s). No PENDING beyond "
                     "7-day SLA. No approvals recorded yet.")
    else:
        evo_score = 2   # Developing — SLA breached
        evo_rat   = (f"{pending_old} proposal(s) past 7-day review SLA "
                     f"of {proposal_total} total.")
    check("Evolution proposals reviewed within 7-day SLA",
          "Lifecycle",
          "Are autonomous ontology-evolution proposals reviewed and resolved within the 7-day SLA?",
          evo_score, evo_rat,
          "ontology_evolution_proposals + ontology_version_ledger")

    # ── Workstream 4: Regulatory AI Compliance Evidence Engine ──────────
    # Criterion: Regulatory Evidence Coverage
    # Scores the share of loaded regulations whose requirements are at
    # least 80% SATISFIED against the current toolkit run.
    try:
        import sys as _sys
        _repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _repo not in _sys.path:
            _sys.path.insert(0, _repo)
        from compliance.mapping import coverage_score as _cov_score
        cov = _cov_score(
            out_path=os.path.join(_repo, "output"),
            db_path=os.path.join(_repo, "db", "enterprise.db"),
        )
        total_regs = cov["total_regulations"]
        pct = cov["coverage_percent"]
        if total_regs == 0:
            reg_score = 0
            reg_rat = ("No regulations loaded under compliance/regulations/. "
                       "Add at least one regulation file to light this gate.")
        elif pct >= 75:
            reg_score = 5
            reg_rat = (f"{cov['regulations_at_80']}/{total_regs} regulations "
                       f"at ≥80% coverage ({pct}% overall).")
        elif pct >= 50:
            reg_score = 4
            reg_rat = (f"{cov['regulations_at_80']}/{total_regs} regulations "
                       f"at ≥80% coverage ({pct}% overall).")
        elif pct >= 25:
            reg_score = 3
            reg_rat = (f"{cov['regulations_at_80']}/{total_regs} regulations "
                       f"at ≥80% coverage ({pct}% overall) — below target.")
        else:
            reg_score = 2
            reg_rat = (f"Only {cov['regulations_at_80']}/{total_regs} "
                       f"regulations at ≥80% coverage — remediation required.")
    except Exception as _e:
        reg_score = 1
        reg_rat = (f"Compliance mapping layer unavailable ({_e}). Run "
                   "`python3 toolkit.py --phase test --phase comply`.")
    check("Regulatory Evidence Coverage", "Compliance",
          "Do loaded regulations have ≥80% of their requirements satisfied?",
          reg_score, reg_rat,
          "compliance/mapping.py: coverage_score()")

    # Criterion: Audit Trail Completeness
    # High-confidence observations without full PROV-O attribution are
    # audit-evidence gaps.
    try:
        hi_conf = qn(
            "SELECT COUNT(*) FROM observations "
            "WHERE confidence_score >= 0.8"
        )
        hi_conf_full = qn(
            "SELECT COUNT(*) FROM observations "
            "WHERE confidence_score >= 0.8 "
            "AND recorded_by IS NOT NULL "
            "AND observed_at IS NOT NULL"
        )
    except Exception:
        hi_conf = 0
        hi_conf_full = 0
    audit_pct = round((hi_conf_full / max(hi_conf, 1)) * 100)
    if hi_conf == 0:
        audit_score = 2
        audit_rat = "No high-confidence observations in the store."
    elif audit_pct >= 95:
        audit_score = 5
        audit_rat = (f"{hi_conf_full}/{hi_conf} high-confidence observations "
                     f"({audit_pct}%) carry full recorded_by + observed_at.")
    elif audit_pct >= 80:
        audit_score = 4
        audit_rat = (f"{hi_conf_full}/{hi_conf} high-confidence observations "
                     f"({audit_pct}%) carry full attribution.")
    else:
        audit_score = 2
        audit_rat = (f"Only {hi_conf_full}/{hi_conf} high-confidence observations "
                     f"({audit_pct}%) carry full attribution — audit gap.")
    check("Audit Trail Completeness", "Compliance",
          "Do high-confidence observations carry complete PROV-O attribution?",
          audit_score, audit_rat,
          "observations.recorded_by + observations.observed_at")

    return scores


# ── CQ Runner ────────────────────────────────────────────────────────────

def run_cq_tests(intro, output_dir: str) -> List[Dict]:
    os.makedirs(output_dir, exist_ok=True)
    results = []
    passed = failed = 0

    # Phase 0: the `sparql_equiv` on every CQ used to be written to CSV and
    # never executed — what ran was the SQL twin, against SQLite. That
    # validates the *database*, not the ontology, while the report implied
    # the ontology had answered. Both are now executed and reported
    # separately, so the gap between them is visible rather than assumed.
    ont_graph = _load_cq_ontology(output_dir)

    print(f"\n  Running {len(COMPETENCY_QUESTIONS)} competency question tests...")
    if ont_graph is None:
        print("    ⚠ Ontology graph unavailable — SPARQL column will read N/A.")

    for cq in COMPETENCY_QUESTIONS:
        try:
            rows = intro._connector.execute(cq["sql"].strip())
            row_count = len(rows)
            passed_test = (row_count > 0) == cq["expected_non_empty"]
            status = "PASS" if passed_test else "FAIL"
            if passed_test:
                passed += 1
            else:
                failed += 1
            sample = str(rows[0]) if rows else "(empty)"
        except Exception as e:
            status = "ERROR"
            row_count = 0
            sample = str(e)
            failed += 1

        sparql_rows, sparql_status = _run_cq_sparql(ont_graph, cq)

        result = {
            "cq_id": cq["id"],
            "priority": cq["priority"],
            "status": status,
            "sql_status": status,
            "sparql_status": sparql_status,
            "question": cq["question"],
            "sparql_equiv": cq["sparql_equiv"],
            "row_count": row_count,
            "sparql_row_count": sparql_rows,
            "sample_result": sample[:120],
            "validates": cq["validates"],
        }
        results.append(result)
        icon = "✓" if status == "PASS" else "✗"
        print(f"    {icon} {cq['id']} [{cq['priority']:8s}] SQL={status:5s} "
              f"SPARQL={sparql_status:7s}  rows={row_count}/{sparql_rows}"
              f"  — {cq['question'][:44]}")

    sparql_answered = sum(1 for r in results if r["sparql_status"] == "PASS")
    print(f"  CQ Tests: {passed} passed, {failed} failed of {len(COMPETENCY_QUESTIONS)} total")
    print(f"    SQL (database) answered: {passed}/{len(COMPETENCY_QUESTIONS)}   "
          f"SPARQL (ontology) answered: {sparql_answered}/{len(COMPETENCY_QUESTIONS)}")
    if sparql_answered < passed:
        print("    ⚠ The database answers more competency questions than the "
              "ontology does.\n      That gap is the ABox gap — see "
              "ONTOLOGY_ROADMAP.md Phase 4.")

    # Write CQ results
    cq_path = os.path.join(output_dir, "cq_test_results.csv")
    with open(cq_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"  ✓ CQ test results       → {cq_path}")

    # Governance scorecard
    scores = _score_governance(intro.conn, [], output_dir)
    gov_path = os.path.join(output_dir, "governance_scorecard.csv")
    with open(gov_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(scores[0].keys()))
        w.writeheader()
        w.writerows(scores)
    avg = sum(s["score"] for s in scores) / len(scores)
    print(f"  ✓ Governance scorecard  → {gov_path}")
    print(f"    Auto-scored criteria: {len(scores)}  |  Average score: {avg:.1f}/5.0")

    return results
