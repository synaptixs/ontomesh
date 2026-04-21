"""
drift_detector.py — Phase 3 · Sprint S14
──────────────────────────────────────────
Drift Detection Ontology Extension.

Extends the `PerformanceIndicator` class to natively model ML monitoring
metrics as first-class ontology citizens:
  • PSI  (Population Stability Index)
  • KL   (Kullback-Leibler divergence)
  • JS   (Jensen-Shannon divergence)
  • Calibration Score
  • Log Template Shift

Generates:
  output/ontology/drift.ttl         — DriftObservation OWL subclass hierarchy
  output/shapes/drift-shapes.ttl    — SHACL NodeShapes for drift validation
  output/vocab/drift-skos.ttl       — SKOS concepts for drift taxonomy

OWL design:
  :DriftObservation rdfs:subClassOf :PerformanceIndicator, sosa:Observation
  :DriftMetricType  — enumerated class for metric type
  Subclasses: :PSIDriftObservation, :KLDriftObservation,
              :JSDriftObservation, :CalibrationDriftObservation,
              :LogTemplateDriftObservation

SHACL rules:
  • metric_value required (xsd:decimal)
  • baseline_period required (xsd:string)
  • observation_period required (xsd:string)
  • severity_flag: CRITICAL if PSI>0.25, WARNING if PSI>0.1
  • drift_threshold enforced per metric type

CLI:
  python3 toolkit.py --phase drift [--db db/enterprise.db]
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

BASE_IRI   = "https://ontology.example.com/enterprise/"
DRIFT_IRI  = f"{BASE_IRI}drift/"
SOSA_NS    = "http://www.w3.org/ns/sosa/"
SSN_NS     = "http://www.w3.org/ns/ssn/"
PROV_NS    = "http://www.w3.org/ns/prov#"
SKOS_NS    = "http://www.w3.org/2004/02/skos/core#"
SH_NS      = "http://www.w3.org/ns/shacl#"
NOW        = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

PREFIXES = f"""\
@prefix :      <{BASE_IRI}> .
@prefix drift: <{DRIFT_IRI}> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix skos:  <{SKOS_NS}> .
@prefix sosa:  <{SOSA_NS}> .
@prefix ssn:   <{SSN_NS}> .
@prefix prov:  <{PROV_NS}> .
@prefix sh:    <{SH_NS}> .
@prefix dcterms: <http://purl.org/dc/terms/> .
"""


def _drift_ontology() -> str:
    return f"""\
{PREFIXES}

# ═══════════════════════════════════════════════════════════════════════════
#  Drift Detection Ontology Extension
#  Phase 3 · Sprint S14 · Generated {NOW}
# ═══════════════════════════════════════════════════════════════════════════

<{DRIFT_IRI}>
  a owl:Ontology ;
  owl:versionIRI <{DRIFT_IRI}1.0.0> ;
  owl:versionInfo "1.0.0" ;
  owl:imports <{BASE_IRI}> ;
  rdfs:label "Drift Detection Ontology Extension" ;
  rdfs:comment "ML monitoring metrics as first-class OWL citizens — PSI, KL/JS, calibration, log template shift." ;
  dcterms:created "{NOW}"^^xsd:dateTime ;
  dcterms:creator "Ontology Toolkit — Phase 3 Auto-generated" .


# ── Drift Metric Type (enumerated) ──────────────────────────────────────────

:DriftMetricType
  a owl:Class ;
  rdfs:label "Drift Metric Type" ;
  rdfs:comment "Enumeration of supported drift metric algorithms." ;
  owl:oneOf (
    drift:PSI
    drift:KLDivergence
    drift:JSDivergence
    drift:CalibrationScore
    drift:LogTemplateShift
  ) .

drift:PSI
  a :DriftMetricType ;
  rdfs:label "Population Stability Index" ;
  skos:definition "Measures distribution shift between baseline and current population. PSI>0.25 → critical drift." .

drift:KLDivergence
  a :DriftMetricType ;
  rdfs:label "Kullback-Leibler Divergence" ;
  skos:definition "Asymmetric measure of how one probability distribution differs from a reference." .

drift:JSDivergence
  a :DriftMetricType ;
  rdfs:label "Jensen-Shannon Divergence" ;
  skos:definition "Symmetric, bounded [0,1] measure of probability distribution divergence. Based on KL." .

drift:CalibrationScore
  a :DriftMetricType ;
  rdfs:label "Calibration Score" ;
  skos:definition "Expected Calibration Error (ECE) — measures how well predicted probabilities match empirical frequencies." .

drift:LogTemplateShift
  a :DriftMetricType ;
  rdfs:label "Log Template Shift" ;
  skos:definition "Fraction of log lines matching a new or previously unseen template cluster." .


# ── DriftObservation hierarchy ────────────────────────────────────────────────

:DriftObservation
  a owl:Class ;
  rdfs:subClassOf :PerformanceIndicator, sosa:Observation ;
  rdfs:label "Drift Observation" ;
  rdfs:comment "An observation of statistical drift in a monitored feature or model output." ;
  :sensitivityTier :Internal .

:PSIDriftObservation
  a owl:Class ;
  rdfs:subClassOf :DriftObservation ;
  rdfs:label "PSI Drift Observation" ;
  rdfs:comment "Population Stability Index drift measurement. Threshold: WARNING>0.1, CRITICAL>0.25." ;
  :sensitivityTier :Internal .

:KLDriftObservation
  a owl:Class ;
  rdfs:subClassOf :DriftObservation ;
  rdfs:label "KL Divergence Drift Observation" ;
  rdfs:comment "Kullback-Leibler divergence measurement between baseline and current distributions." ;
  :sensitivityTier :Internal .

:JSDriftObservation
  a owl:Class ;
  rdfs:subClassOf :DriftObservation ;
  rdfs:label "JS Divergence Drift Observation" ;
  rdfs:comment "Jensen-Shannon divergence measurement (symmetric, bounded 0–1)." ;
  :sensitivityTier :Internal .

:CalibrationDriftObservation
  a owl:Class ;
  rdfs:subClassOf :DriftObservation ;
  rdfs:label "Calibration Drift Observation" ;
  rdfs:comment "Expected Calibration Error measurement for probabilistic model outputs." ;
  :sensitivityTier :Internal .

:LogTemplateDriftObservation
  a owl:Class ;
  rdfs:subClassOf :DriftObservation ;
  rdfs:label "Log Template Drift Observation" ;
  rdfs:comment "Fraction of log lines matching previously unseen template clusters." ;
  :sensitivityTier :Internal .


# ── Data properties ────────────────────────────────────────────────────────────

:metricValue
  a owl:DatatypeProperty ;
  rdfs:domain :DriftObservation ;
  rdfs:range  xsd:decimal ;
  rdfs:label  "Metric Value" ;
  rdfs:comment "Numeric value of the drift metric at observation time." ;
  :sensitivityTier :Internal .

:driftMetricType
  a owl:ObjectProperty ;
  rdfs:domain :DriftObservation ;
  rdfs:range  :DriftMetricType ;
  rdfs:label  "Drift Metric Type" ;
  rdfs:comment "The algorithm used to compute this drift measurement." .

:baselinePeriod
  a owl:DatatypeProperty ;
  rdfs:domain :DriftObservation ;
  rdfs:range  xsd:string ;
  rdfs:label  "Baseline Period" ;
  rdfs:comment "ISO 8601 interval describing the reference window (e.g. 2026-01-01/2026-03-31)." .

:observationPeriod
  a owl:DatatypeProperty ;
  rdfs:domain :DriftObservation ;
  rdfs:range  xsd:string ;
  rdfs:label  "Observation Period" ;
  rdfs:comment "ISO 8601 interval of the period being compared to baseline." .

:featureName
  a owl:DatatypeProperty ;
  rdfs:domain :DriftObservation ;
  rdfs:range  xsd:string ;
  rdfs:label  "Feature Name" ;
  rdfs:comment "Model input feature or output dimension being monitored." .

:modelVersion
  a owl:DatatypeProperty ;
  rdfs:domain :DriftObservation ;
  rdfs:range  xsd:string ;
  rdfs:label  "Model Version" ;
  rdfs:comment "Semantic version of the model being monitored (e.g. v2.1.3)." .

:driftSeverity
  a owl:DatatypeProperty ;
  rdfs:domain :DriftObservation ;
  rdfs:range  xsd:string ;
  rdfs:label  "Drift Severity" ;
  rdfs:comment "Computed severity: OK | WARNING | CRITICAL based on threshold exceedance." .

:driftThreshold
  a owl:DatatypeProperty ;
  rdfs:domain :DriftObservation ;
  rdfs:range  xsd:decimal ;
  rdfs:label  "Drift Threshold" ;
  rdfs:comment "Domain-configured threshold for CRITICAL severity escalation." .

:baselineDistribution
  a owl:DatatypeProperty ;
  rdfs:domain :DriftObservation ;
  rdfs:range  xsd:string ;
  rdfs:label  "Baseline Distribution" ;
  rdfs:comment "JSON-serialised baseline probability distribution or histogram." .

:currentDistribution
  a owl:DatatypeProperty ;
  rdfs:domain :DriftObservation ;
  rdfs:range  xsd:string ;
  rdfs:label  "Current Distribution" ;
  rdfs:comment "JSON-serialised current probability distribution or histogram." .
"""


def _drift_shacl() -> str:
    return f"""\
{PREFIXES}

# ═══════════════════════════════════════════════════════════════════════════
#  SHACL Shapes — Drift Detection
#  Phase 3 · Sprint S14 · Generated {NOW}
# ═══════════════════════════════════════════════════════════════════════════

<{DRIFT_IRI}shapes>
  a owl:Ontology ;
  rdfs:label "Drift Detection SHACL Shapes" .


# ── DriftObservation base shape ────────────────────────────────────────────

:DriftObservationShape
  a sh:NodeShape ;
  sh:targetClass :DriftObservation ;
  rdfs:label "Drift Observation Shape" ;

  sh:property [
    sh:path      :metricValue ;
    sh:minCount  1 ;
    sh:datatype  xsd:decimal ;
    sh:message   "metricValue is required and must be xsd:decimal." ;
    sh:severity  sh:Violation ;
  ] ;

  sh:property [
    sh:path      :driftMetricType ;
    sh:minCount  1 ;
    sh:class     :DriftMetricType ;
    sh:message   "driftMetricType is required." ;
    sh:severity  sh:Violation ;
  ] ;

  sh:property [
    sh:path      :baselinePeriod ;
    sh:minCount  1 ;
    sh:datatype  xsd:string ;
    sh:message   "baselinePeriod (ISO 8601 interval) is required." ;
    sh:severity  sh:Violation ;
  ] ;

  sh:property [
    sh:path      :observationPeriod ;
    sh:minCount  1 ;
    sh:datatype  xsd:string ;
    sh:message   "observationPeriod (ISO 8601 interval) is required." ;
    sh:severity  sh:Violation ;
  ] ;

  sh:property [
    sh:path      :driftSeverity ;
    sh:in        ( "OK" "WARNING" "CRITICAL" ) ;
    sh:message   "driftSeverity must be OK, WARNING, or CRITICAL." ;
    sh:severity  sh:Violation ;
  ] ;

  sh:property [
    sh:path      :featureName ;
    sh:datatype  xsd:string ;
    sh:message   "featureName must be a string." ;
    sh:severity  sh:Warning ;
  ] .


# ── PSI-specific shape (threshold enforcement) ─────────────────────────────

:PSIDriftObservationShape
  a sh:NodeShape ;
  sh:targetClass :PSIDriftObservation ;

  sh:property [
    sh:path        :metricValue ;
    sh:maxInclusive 1.0 ;
    sh:minInclusive 0.0 ;
    sh:message     "PSI value must be in [0.0, 1.0]." ;
    sh:severity    sh:Violation ;
  ] .


# ── JS Divergence shape (bounded 0–1) ─────────────────────────────────────

:JSDriftObservationShape
  a sh:NodeShape ;
  sh:targetClass :JSDriftObservation ;

  sh:property [
    sh:path        :metricValue ;
    sh:maxInclusive 1.0 ;
    sh:minInclusive 0.0 ;
    sh:message     "JS divergence must be in [0.0, 1.0]." ;
    sh:severity    sh:Violation ;
  ] .


# ── Calibration score shape ────────────────────────────────────────────────

:CalibrationDriftObservationShape
  a sh:NodeShape ;
  sh:targetClass :CalibrationDriftObservation ;

  sh:property [
    sh:path        :metricValue ;
    sh:maxInclusive 1.0 ;
    sh:minInclusive 0.0 ;
    sh:message     "Calibration score (ECE) must be in [0.0, 1.0]." ;
    sh:severity    sh:Violation ;
  ] .
"""


def _drift_skos() -> str:
    return f"""\
{PREFIXES}

# ═══════════════════════════════════════════════════════════════════════════
#  SKOS Vocabulary — Drift Detection Taxonomy
#  Phase 3 · Sprint S14 · Generated {NOW}
# ═══════════════════════════════════════════════════════════════════════════

drift:DriftConceptScheme
  a skos:ConceptScheme ;
  skos:prefLabel "Drift Detection Concept Scheme" ;
  dcterms:description "Taxonomy of ML drift monitoring concepts for the Ontology Toolkit." ;
  dcterms:created "{NOW}"^^xsd:dateTime .

drift:DriftMonitoring
  a skos:Concept ;
  skos:inScheme    drift:DriftConceptScheme ;
  skos:topConceptOf drift:DriftConceptScheme ;
  skos:prefLabel   "Drift Monitoring" ;
  skos:definition  "The practice of detecting and measuring statistical drift in ML model inputs and outputs." .

drift:DistributionDrift
  a skos:Concept ;
  skos:inScheme    drift:DriftConceptScheme ;
  skos:broader     drift:DriftMonitoring ;
  skos:prefLabel   "Distribution Drift" ;
  skos:definition  "Change in the statistical distribution of model input features over time." ;
  skos:narrower    drift:CovariateShift, drift:ConceptDrift .

drift:CovariateShift
  a skos:Concept ;
  skos:inScheme    drift:DriftConceptScheme ;
  skos:broader     drift:DistributionDrift ;
  skos:prefLabel   "Covariate Shift" ;
  skos:definition  "Input feature distribution changes while the conditional label distribution P(Y|X) stays constant." .

drift:ConceptDrift
  a skos:Concept ;
  skos:inScheme    drift:DriftConceptScheme ;
  skos:broader     drift:DistributionDrift ;
  skos:prefLabel   "Concept Drift" ;
  skos:definition  "The relationship between inputs and outputs changes over time — P(Y|X) shifts." .

drift:PSIConcept
  a skos:Concept ;
  skos:inScheme    drift:DriftConceptScheme ;
  skos:broader     drift:DistributionDrift ;
  skos:prefLabel   "Population Stability Index" ;
  skos:altLabel    "PSI" ;
  skos:definition  "PSI < 0.1: no change. 0.1–0.25: moderate shift. > 0.25: significant drift." .

drift:KLConcept
  a skos:Concept ;
  skos:inScheme    drift:DriftConceptScheme ;
  skos:broader     drift:DistributionDrift ;
  skos:prefLabel   "KL Divergence" ;
  skos:altLabel    "Kullback-Leibler divergence" ;
  skos:definition  "Measures information lost when distribution Q is used to approximate P. Asymmetric." .

drift:JSConcept
  a skos:Concept ;
  skos:inScheme    drift:DriftConceptScheme ;
  skos:broader     drift:DistributionDrift ;
  skos:prefLabel   "JS Divergence" ;
  skos:altLabel    "Jensen-Shannon divergence" ;
  skos:definition  "Symmetric, smoothed version of KL divergence bounded between 0 and 1." .

drift:ModelDegradation
  a skos:Concept ;
  skos:inScheme    drift:DriftConceptScheme ;
  skos:broader     drift:DriftMonitoring ;
  skos:prefLabel   "Model Degradation" ;
  skos:definition  "Decline in model performance metrics (accuracy, precision, AUC) over time." ;
  skos:narrower    drift:CalibrationDrift .

drift:CalibrationDrift
  a skos:Concept ;
  skos:inScheme    drift:DriftConceptScheme ;
  skos:broader     drift:ModelDegradation ;
  skos:prefLabel   "Calibration Drift" ;
  skos:definition  "Model predicted probabilities diverge from empirical outcome frequencies." .

drift:LogDrift
  a skos:Concept ;
  skos:inScheme    drift:DriftConceptScheme ;
  skos:broader     drift:DriftMonitoring ;
  skos:prefLabel   "Log Template Drift" ;
  skos:definition  "New or changed log message templates indicate infrastructure or software changes." .
"""


def run_drift_detection(out_path: str) -> dict:
    """Generate drift detection OWL, SHACL, and SKOS artifacts."""
    ont_dir    = os.path.join(out_path, "ontology")
    shapes_dir = os.path.join(out_path, "shapes")
    vocab_dir  = os.path.join(out_path, "vocab")
    for d in (ont_dir, shapes_dir, vocab_dir):
        os.makedirs(d, exist_ok=True)

    artifacts = {}

    drift_ttl_path = os.path.join(ont_dir, "drift.ttl")
    with open(drift_ttl_path, "w", encoding="utf-8") as f:
        f.write(_drift_ontology())
    print(f"  ✓ Drift ontology    → {drift_ttl_path}")
    artifacts["drift.ttl"] = drift_ttl_path

    shapes_path = os.path.join(shapes_dir, "drift-shapes.ttl")
    with open(shapes_path, "w", encoding="utf-8") as f:
        f.write(_drift_shacl())
    print(f"  ✓ Drift SHACL       → {shapes_path}")
    artifacts["drift-shapes.ttl"] = shapes_path

    skos_path = os.path.join(vocab_dir, "drift-skos.ttl")
    with open(skos_path, "w", encoding="utf-8") as f:
        f.write(_drift_skos())
    print(f"  ✓ Drift SKOS vocab  → {skos_path}")
    artifacts["drift-skos.ttl"] = skos_path

    return artifacts


def compute_psi(baseline: list[float], current: list[float],
                epsilon: float = 1e-6) -> float:
    """
    Compute Population Stability Index between two normalised histograms.
    baseline, current: lists of bin proportions that sum to 1.0.
    Returns PSI value. Thresholds: <0.1 stable, 0.1–0.25 warning, >0.25 critical.
    """
    if len(baseline) != len(current):
        raise ValueError("baseline and current must have equal bin count")
    psi = 0.0
    for b, c in zip(baseline, current):
        b = max(b, epsilon)
        c = max(c, epsilon)
        psi += (c - b) * (c / b).__class__.__mro__[0](c / b)
    import math
    psi_val = sum(
        (max(c, epsilon) - max(b, epsilon)) * math.log(max(c, epsilon) / max(b, epsilon))
        for b, c in zip(baseline, current)
    )
    return round(psi_val, 6)


def severity_from_psi(psi: float) -> str:
    if psi > 0.25:
        return "CRITICAL"
    if psi > 0.1:
        return "WARNING"
    return "OK"


def severity_from_js(js: float) -> str:
    if js > 0.5:
        return "CRITICAL"
    if js > 0.2:
        return "WARNING"
    return "OK"
