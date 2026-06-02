"""
src/targets — T1.5 multi-target generation.

The ontology becomes a *generator*: one source-of-truth
(``GenerationContext``) feeds multiple target adapters that emit
Cypher, GraphQL SDL, detection rules, etc., alongside the existing
OWL/SHACL artefacts.

Usage::

    from targets import GenerationContext, render_targets
    ctx = GenerationContext.from_introspector(intro, session=session)
    outputs = render_targets(ctx, names=["cypher", "graphql", "detection_rules"])
    # outputs: { "cypher/schema.cypher": "<text>", ... }
"""

from .base import GenerationContext, Target, TargetResult
from .registry import (
    AVAILABLE_TARGETS, render_targets, get_target,
)
from .cypher import CypherTarget
from .graphql import GraphQLTarget
from .detection_rules import DetectionRulesTarget

__all__ = [
    "GenerationContext", "Target", "TargetResult",
    "AVAILABLE_TARGETS", "render_targets", "get_target",
    "CypherTarget", "GraphQLTarget", "DetectionRulesTarget",
]
