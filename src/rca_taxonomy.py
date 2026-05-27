"""
rca_taxonomy.py — Phase L5.1
────────────────────────────
Static OWL taxonomy fragment that gives downstream reasoning + Insights
queries a shared vocabulary for root-cause analysis.

The fragment is rendered before the generated domain classes by
:func:`ontology_generator.generate_ontology`. It declares:

  :CausalEvent       — superclass of every event that can participate
                       in a causal chain. Log-derived event classes
                       (L4 approvals) are emitted as rdfs:subClassOf
                       :CausalEvent so :hasCause works uniformly.
  :hasCause          — object property pointing from an effect event
                       to one of its causes.
  :triggers          — inverse of :hasCause (cause → effect direction).
  :precededBy        — transitive temporal ordering (effect precededBy
                       cause precededBy earlier-cause).
  :rootCause         — derived sub-property of :hasCause: the cause
                       that has no further :hasCause edge of its own.
                       Materialised by a SPARQL CONSTRUCT (L6 starter
                       library) over the closure of :hasCause.

Time-interval data properties (:startedAt, :endedAt, :duration) and
the severity-tier mapping are emitted per log-derived class by
:mod:`ontology_generator`, not here — they're per-class signals, not
taxonomy-level.

Pure-string emitter, no rdflib dependency. The string is concatenated
into ``enterprise.ttl`` between the base classes and the domain
classes so reasoners see it during classification.
"""

from __future__ import annotations


_TAXONOMY_TTL = """\
# ── RCA Taxonomy (Phase L5) ─────────────────────────────────────────
# Imported automatically when any session.events / session.causal_rules
# carries source=log-discovery. The taxonomy is the shared vocabulary
# every log-derived event class plugs into so :hasCause / :rootCause
# queries work uniformly across services.

:CausalEvent
  a owl:Class ;
  rdfs:subClassOf :DomainEvent ;
  rdfs:label "Causal Event" ;
  rdfs:comment "An event that can participate in a causal chain. Every log-derived event class is a rdfs:subClassOf :CausalEvent." ;
  :sensitivityTier :Internal .

:hasCause
  a owl:ObjectProperty ;
  rdfs:label "has cause" ;
  rdfs:domain :CausalEvent ;
  rdfs:range :CausalEvent ;
  rdfs:comment "Effect to cause. Materialised by Phase B from approved LOG_CAUSAL_EDGE proposals plus the L6 rule library." ;
  :sensitivityTier :Internal .

:triggers
  a owl:ObjectProperty ;
  rdfs:label "triggers" ;
  rdfs:domain :CausalEvent ;
  rdfs:range :CausalEvent ;
  owl:inverseOf :hasCause ;
  rdfs:comment "Cause to effect. Inverse of :hasCause." ;
  :sensitivityTier :Internal .

:precededBy
  a owl:ObjectProperty, owl:TransitiveProperty ;
  rdfs:label "preceded by" ;
  rdfs:domain :CausalEvent ;
  rdfs:range :CausalEvent ;
  rdfs:comment "Temporal precedence, weaker than :hasCause. Transitive: A precededBy B and B precededBy C implies A precededBy C under OWL-RL." ;
  :sensitivityTier :Internal .

:rootCause
  a owl:ObjectProperty ;
  rdfs:subPropertyOf :hasCause ;
  rdfs:label "root cause" ;
  rdfs:domain :CausalEvent ;
  rdfs:range :CausalEvent ;
  rdfs:comment "The terminal cause in a chain. Derived in Phase B by the L6 starter rule." ;
  :sensitivityTier :Internal .

:occurredAtService
  a owl:DatatypeProperty ;
  rdfs:label "occurred at service" ;
  rdfs:domain :CausalEvent ;
  rdfs:range xsd:string ;
  rdfs:comment "Service identifier the event originated from. Set automatically on log-derived events." ;
  :sensitivityTier :Internal .

"""


def emit_taxonomy() -> str:
    """Return the static taxonomy Turtle fragment."""
    return _TAXONOMY_TTL


__all__ = ["emit_taxonomy"]
